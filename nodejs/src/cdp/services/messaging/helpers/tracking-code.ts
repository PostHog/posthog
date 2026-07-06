import crypto from 'node:crypto'
import { Counter } from 'prom-client'

import { CyclotronJobInvocationHogFunction } from '~/cdp/types'

const SIGNATURE_BYTES = 16

// Custom MIME header carrying the signed tracking code. HMAC adds ~23 chars to the code,
// which pushes a batch-flow code past the SES `EmailTags` 256-char cap. Header values have
// no such limit, so the signed code rides here; the SES tag carries the short unsigned code
// (see generateShort) purely as a backwards-compat fallback.
export const TRACKING_CODE_HEADER_NAME = 'X-PostHog-Tracking-Code'

// Tracks the rotation curve from unsigned to signed tracking codes.
export const trackingCodeFormatCounter = new Counter({
    name: 'email_tracking_code_format_total',
    help: 'Count of email tracking codes parsed by signature format',
    labelNames: ['format', 'source'],
})

// Mint-time signal: counts every code generate() produces, labelled by whether a signing key was
// available. Unlike the parse-time counter above (which only sees codes that come back via the SES
// webhook or click endpoints), this fires on the send path itself, so a sustained `unsigned` rate
// pinpoints an email-sending deployment running without ENCRYPTION_SALT_KEYS. Watching this reach
// zero is the prerequisite for making generate() fail closed (#62624). Note it counts per generate()
// call (header + pixel + each redirect link), not per email, so it is a rate signal, not an email count.
export const trackingCodeMintCounter = new Counter({
    name: 'email_tracking_code_mint_total',
    help: 'Count of email tracking codes minted by signature format (signed when a key is configured)',
    labelNames: ['format'],
})

function toBase64UrlSafe(input: string | Buffer): string {
    const b64 = Buffer.isBuffer(input) ? input.toString('base64') : Buffer.from(input, 'utf8').toString('base64')
    return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fromBase64UrlSafeBuffer(b64url: string): Buffer {
    let b64 = b64url.replace(/-/g, '+').replace(/_/g, '/')
    while (b64.length % 4) {
        b64 += '='
    }
    return Buffer.from(b64, 'base64')
}

function fromBase64UrlSafe(b64url: string): string {
    return fromBase64UrlSafeBuffer(b64url).toString('utf8')
}

export type TrackingInvocation = Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id' | 'teamId'> & {
    parentRunId?: string | null
    state?: { actionId?: string }
    distinctId?: string
}

export type TrackingCodeFormat = 'signed' | 'unsigned'

export type ParsedTrackingCode = {
    functionId: string
    invocationId: string
    teamId: string
    actionId?: string
    parentRunId?: string
    isTest: boolean
    distinctId?: string
    format: TrackingCodeFormat
}

// Generates, signs, verifies and renders email tracking codes. Signing keys and the public
// tracking URL are read once in the constructor so callers can be injected with a configured
// instance (see cdp-services.ts) instead of reaching into global config — and tests can pass
// keys directly rather than mutating `defaultConfig`.
export class EmailTrackingCodeSigner {
    private signingKeys: string[]

    constructor(
        encryptionSaltKeys: string,
        private trackingUrl: string
    ) {
        this.signingKeys = (encryptionSaltKeys || '')
            .split(',')
            .map((key) => key.trim())
            .filter(Boolean)
    }

    private signPayload(payload: string, key: string): string {
        const mac = crypto.createHmac('sha256', key).update(payload).digest().subarray(0, SIGNATURE_BYTES)
        return toBase64UrlSafe(mac)
    }

    private verifySignature(payload: string, signature: string): boolean {
        const expected = fromBase64UrlSafeBuffer(signature)
        if (expected.length !== SIGNATURE_BYTES) {
            return false
        }
        // Accept a signature made with any configured key so key rotation doesn't invalidate
        // in-flight codes signed with the previous key.
        for (const key of this.signingKeys) {
            const candidate = crypto.createHmac('sha256', key).update(payload).digest().subarray(0, SIGNATURE_BYTES)
            if (crypto.timingSafeEqual(expected, candidate)) {
                return true
            }
        }
        return false
    }

    parse(encodedTrackingCode: string): ParsedTrackingCode | null {
        if (!encodedTrackingCode) {
            return null
        }

        let payloadB64 = encodedTrackingCode
        let format: TrackingCodeFormat = 'unsigned'

        const parts = encodedTrackingCode.split('.')
        if (parts.length > 1) {
            // A legitimate signed code is exactly `<payload>.<signature>`; both halves are base64url
            // (no dots), so any code with more than one `.` is malformed and rejected outright.
            if (parts.length !== 2 || !this.verifySignature(parts[0], parts[1])) {
                return null
            }
            payloadB64 = parts[0]
            format = 'signed'
        }

        try {
            const decoded = fromBase64UrlSafe(payloadB64)
            // distinctId is the trailing segment and may itself contain colons, so rejoin everything past it.
            const [functionId, invocationId, teamId, actionId, parentRunId, isTest, ...distinctIdParts] =
                decoded.split(':')
            if (!functionId || !invocationId) {
                return null
            }
            return {
                functionId,
                invocationId,
                teamId,
                actionId: actionId || undefined,
                parentRunId: parentRunId || undefined,
                isTest: isTest === '1',
                // Only trust distinct_id from a signed code — the HMAC is its integrity guarantee. The
                // legitimate unsigned tag never carries a distinct_id, so an unsigned code with one is
                // forged; honoring it would let a crafted ph_id inject engagement events for any team.
                distinctId:
                    format === 'signed' && distinctIdParts.length > 0
                        ? distinctIdParts.join(':') || undefined
                        : undefined,
                format,
            }
        } catch {
            return null
        }
    }

    // Full tracking code, HMAC-signed when a signing key is configured. Rides in the custom MIME
    // header and the pixel/link URLs — carriers with no length cap — and the signature lets the
    // public tracking endpoint reject forged `ph_id` values.
    generate(invocation: TrackingInvocation, isTest = false): string {
        const actionId = invocation.state?.actionId ?? ''
        const parentRunId = invocation.parentRunId ?? ''
        const distinctId = invocation.distinctId ?? ''
        // isTest marks sends from the editor's "Run test" so the SES webhook can skip recording their
        // metrics — keeping test traffic out of the production Metrics tab. distinctId is appended last
        // because it may contain colons; it attributes engagement events.
        const payload = toBase64UrlSafe(
            `${invocation.functionId}:${invocation.id}:${invocation.teamId}:${actionId}:${parentRunId}:${isTest ? '1' : ''}:${distinctId}`
        )
        if (this.signingKeys.length === 0) {
            // Fail open while signing rolls out so sends never break; tighten to throw once enforced (#62624).
            // The mint counter makes this branch observable so we can confirm it is never hit in prod
            // before flipping to fail-closed.
            trackingCodeMintCounter.inc({ format: 'unsigned' })
            return payload
        }
        trackingCodeMintCounter.inc({ format: 'signed' })
        return `${payload}.${this.signPayload(payload, this.signingKeys[0])}`
    }

    // Unsigned tracking code for the SES `EmailTags` carrier. Omitting the signature keeps the
    // value short enough to stay within the 256-char tag cap; the tag arrives via the SNS webhook,
    // which is already integrity-protected by SNS signing, so it does not need its own signature.
    // This is a legacy backwards-compat carrier only — new fields (e.g. isTest, distinctId) live on
    // the signed code in generate, which the webhook reads first.
    generateShort(invocation: TrackingInvocation): string {
        const actionId = invocation.state?.actionId ?? ''
        const parentRunId = invocation.parentRunId ?? ''
        return toBase64UrlSafe(
            `${invocation.functionId}:${invocation.id}:${invocation.teamId}:${actionId}:${parentRunId}`
        )
    }

    pixelUrl(invocation: TrackingInvocation, isTest = false): string {
        return `${this.trackingUrl}/public/m/pixel?ph_id=${this.generate(invocation, isTest)}`
    }

    redirectUrl(invocation: TrackingInvocation, targetUrl: string, isTest = false): string {
        return `${this.trackingUrl}/public/m/redirect?ph_id=${this.generate(invocation, isTest)}&target=${encodeURIComponent(targetUrl)}`
    }
}

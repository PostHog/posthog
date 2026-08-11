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
// webhook or click endpoints), this fires on the send path itself. Now that generate() fails closed,
// an `unsigned` sample means a keyless deployment attempted a mint right before the send was refused —
// a config alarm, not a benign tail. Note it counts per generate() call (header + pixel + each redirect
// link), not per email, so it is a rate signal, not an email count.
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
    // Version of the workflow config that sent this email. Engagement metrics (delivered, opened,
    // bounced, complaints) arrive from SES long after the send, by which time the workflow may have
    // been republished — so the sending version has to travel with the message rather than being
    // looked up on arrival. Absent for hog function sends, which have no version.
    workflowVersion?: number
}

export type TrackingCodeFormat = 'signed' | 'unsigned'

// Parses the comma-separated ENCRYPTION_SALT_KEYS into the usable key list. Shared by the signer
// and the boot-time guard so "is a signing key configured?" has a single definition.
function parseSigningKeys(encryptionSaltKeys: string): string[] {
    return (encryptionSaltKeys || '')
        .split(',')
        .map((key) => key.trim())
        .filter(Boolean)
}

// Whether at least one email tracking-code signing key is configured. The boot-time guard uses this
// to refuse to start an email-sending deployment that would otherwise mint unsigned tracking links.
export function hasEmailSigningKey(encryptionSaltKeys: string): boolean {
    return parseSigningKeys(encryptionSaltKeys).length > 0
}

export type ParsedTrackingCode = {
    functionId: string
    invocationId: string
    teamId: string
    actionId?: string
    parentRunId?: string
    isTest: boolean
    distinctId?: string
    workflowVersion?: number
    format: TrackingCodeFormat
}

// Leading segment marking a payload that carries the `workflowVersion` field. The payload is
// positional and `distinctId` is the greedy trailing segment, so a new field can't just be appended
// without shifting distinctId out from under codes minted before it existed — and opens and clicks
// arrive for weeks after a send. The marker lets both layouts coexist: no marker means the original
// layout and no version. It can't collide with a real payload because segment 0 is a UUID.
const VERSIONED_PAYLOAD_MARKER = 'v2'

// Phase one of a two-phase rollout: `parse` understands the marker, `generate` does not yet emit it.
// The layouts are only compatible in one direction — a marked code read by a pod still running the
// old parser shifts every field (functionId becomes the literal marker), the flow lookup misses, and
// the engagement metric is dropped. Emitting before the fleet can parse would lose metrics for the
// length of the rolling deploy.
//
// Phase two flips this to `true` in a follow-up, once this parser is everywhere. Until then no
// engagement metric carries a version, and they land in the version-agnostic series alone.
const EMIT_VERSIONED_PAYLOAD = false

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
        this.signingKeys = parseSigningKeys(encryptionSaltKeys)
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
            const segments = decoded.split(':')
            const isVersioned = segments[0] === VERSIONED_PAYLOAD_MARKER
            const fields = isVersioned ? segments.slice(1) : segments
            // distinctId is the trailing segment and may itself contain colons, so rejoin everything past it.
            const [functionId, invocationId, teamId, actionId, parentRunId, isTest] = fields
            const distinctIdParts = fields.slice(isVersioned ? 7 : 6)
            if (!functionId || !invocationId) {
                return null
            }
            // Signed-only for the same reason as distinct_id below: `generate` always signs, and the
            // unsigned tag carrier never mints a version, so a version on an unsigned code is forged.
            const workflowVersion = isVersioned && format === 'signed' ? Number.parseInt(fields[6], 10) : Number.NaN
            return {
                functionId,
                invocationId,
                teamId,
                actionId: actionId || undefined,
                parentRunId: parentRunId || undefined,
                isTest: isTest === '1',
                // Empty for hog function sends, which have no version.
                workflowVersion:
                    Number.isInteger(workflowVersion) && workflowVersion >= 1 ? workflowVersion : undefined,
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
    generate(invocation: TrackingInvocation, isTest = false, emitVersionedPayload = EMIT_VERSIONED_PAYLOAD): string {
        const actionId = invocation.state?.actionId ?? ''
        const parentRunId = invocation.parentRunId ?? ''
        const distinctId = invocation.distinctId ?? ''
        const workflowVersion = typeof invocation.workflowVersion === 'number' ? String(invocation.workflowVersion) : ''
        // isTest marks sends from the editor's "Run test" so the SES webhook can skip recording their
        // metrics — keeping test traffic out of the production Metrics tab. distinctId is appended last
        // because it may contain colons; it attributes engagement events.
        const fields = [
            invocation.functionId,
            invocation.id,
            invocation.teamId,
            actionId,
            parentRunId,
            isTest ? '1' : '',
        ]
        const payload = toBase64UrlSafe(
            emitVersionedPayload
                ? [VERSIONED_PAYLOAD_MARKER, ...fields, workflowVersion, distinctId].join(':')
                : [...fields, distinctId].join(':')
        )
        if (this.signingKeys.length === 0) {
            // Fail closed (#62624): a deployment with no signing key must never mint unsigned tracking
            // links. Email-sending deployments are guarded at boot (see hasEmailSigningKey), so this is
            // unreachable in prod; the counter still records the attempt before we refuse, keeping the
            // failure attributable if the guard is ever bypassed.
            trackingCodeMintCounter.inc({ format: 'unsigned' })
            throw new Error(
                'Cannot mint email tracking code: no signing key configured (ENCRYPTION_SALT_KEYS is empty)'
            )
        }
        trackingCodeMintCounter.inc({ format: 'signed' })
        return `${payload}.${this.signPayload(payload, this.signingKeys[0])}`
    }

    // Unsigned tracking code for the SES `EmailTags` carrier. Omitting the signature keeps the
    // value short enough to stay within the 256-char tag cap; the tag arrives via the SNS webhook,
    // which is already integrity-protected by SNS signing, so it does not need its own signature.
    // This is a legacy backwards-compat carrier only — new fields (e.g. isTest, distinctId,
    // workflowVersion) live on the signed code in generate, which the webhook reads first. A message
    // that only has this carrier therefore has no version, and its engagement metrics land in the
    // version-agnostic series alone rather than being attributed to a guess.
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

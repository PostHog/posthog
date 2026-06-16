import crypto from 'node:crypto'
import { Counter } from 'prom-client'

import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { defaultConfig } from '~/config/config'

const SIGNATURE_BYTES = 16

// Custom MIME header carrying the signed tracking code. HMAC adds ~23 chars to the code,
// which pushes a batch-flow code past the SES `EmailTags` 256-char cap. Header values have
// no such limit, so the signed code rides here; the SES tag carries the short unsigned code
// (see generateShortEmailTrackingCode) purely as a backwards-compat fallback.
export const TRACKING_CODE_HEADER_NAME = 'X-PostHog-Tracking-Code'

// Tracks the rotation curve from unsigned to signed tracking codes.
export const trackingCodeFormatCounter = new Counter({
    name: 'email_tracking_code_format_total',
    help: 'Count of email tracking codes parsed by signature format',
    labelNames: ['format', 'source'],
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

function getSigningKeys(): string[] {
    return (defaultConfig.ENCRYPTION_SALT_KEYS || '')
        .split(',')
        .map((key) => key.trim())
        .filter(Boolean)
}

function signPayload(payload: string, key: string): string {
    const mac = crypto.createHmac('sha256', key).update(payload).digest().subarray(0, SIGNATURE_BYTES)
    return toBase64UrlSafe(mac)
}

function verifySignature(payload: string, signature: string): boolean {
    const expected = fromBase64UrlSafeBuffer(signature)
    if (expected.length !== SIGNATURE_BYTES) {
        return false
    }
    for (const key of getSigningKeys()) {
        const candidate = crypto.createHmac('sha256', key).update(payload).digest().subarray(0, SIGNATURE_BYTES)
        if (crypto.timingSafeEqual(expected, candidate)) {
            return true
        }
    }
    return false
}

type TrackingInvocation = Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id' | 'teamId'> & {
    parentRunId?: string | null
    state?: { actionId?: string }
}

export type TrackingCodeFormat = 'signed' | 'unsigned'

export const parseEmailTrackingCode = (
    encodedTrackingCode: string
): {
    functionId: string
    invocationId: string
    teamId: string
    actionId?: string
    parentRunId?: string
    isTest: boolean
    format: TrackingCodeFormat
} | null => {
    if (!encodedTrackingCode) {
        return null
    }

    let payloadB64 = encodedTrackingCode
    let format: TrackingCodeFormat = 'unsigned'

    const parts = encodedTrackingCode.split('.')
    if (parts.length > 1) {
        // A legitimate signed code is exactly `<payload>.<signature>`; both halves are base64url
        // (no dots), so any code with more than one `.` is malformed and rejected outright.
        if (parts.length !== 2 || !verifySignature(parts[0], parts[1])) {
            return null
        }
        payloadB64 = parts[0]
        format = 'signed'
    }

    try {
        const decoded = fromBase64UrlSafe(payloadB64)
        const [functionId, invocationId, teamId, actionId, parentRunId, isTest] = decoded.split(':')
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
            format,
        }
    } catch {
        return null
    }
}

// Full tracking code, HMAC-signed when a signing key is configured. Rides in the custom MIME
// header and the pixel/link URLs — carriers with no length cap — and the signature lets the
// public tracking endpoint reject forged `ph_id` values.
export const generateEmailTrackingCode = (invocation: TrackingInvocation, isTest = false): string => {
    const actionId = invocation.state?.actionId ?? ''
    const parentRunId = invocation.parentRunId ?? ''
    // isTest marks sends from the editor's "Run test" so the SES webhook can skip recording
    // their metrics — keeping test traffic out of the production Metrics tab.
    const payload = toBase64UrlSafe(
        `${invocation.functionId}:${invocation.id}:${invocation.teamId}:${actionId}:${parentRunId}:${isTest ? '1' : ''}`
    )
    const keys = getSigningKeys()
    if (keys.length === 0) {
        // Fail open while signing rolls out so sends never break; tighten to throw once enforced (#62624).
        return payload
    }
    return `${payload}.${signPayload(payload, keys[0])}`
}

// Unsigned tracking code for the SES `EmailTags` carrier. Omitting the signature keeps the
// value short enough to stay within the 256-char tag cap; the tag arrives via the SNS webhook,
// which is already integrity-protected by SNS signing, so it does not need its own signature.
// This is a legacy backwards-compat carrier only — new fields (e.g. isTest) live on the signed
// code in generateEmailTrackingCode, which the webhook reads first.
export const generateShortEmailTrackingCode = (invocation: TrackingInvocation): string => {
    const actionId = invocation.state?.actionId ?? ''
    const parentRunId = invocation.parentRunId ?? ''
    return toBase64UrlSafe(`${invocation.functionId}:${invocation.id}:${invocation.teamId}:${actionId}:${parentRunId}`)
}

export const generateEmailTrackingPixelUrl = (invocation: TrackingInvocation, isTest = false): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/pixel?ph_id=${generateEmailTrackingCode(invocation, isTest)}`
}

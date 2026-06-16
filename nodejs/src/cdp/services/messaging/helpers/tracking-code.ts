import crypto from 'node:crypto'
import { Counter } from 'prom-client'

import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { defaultConfig } from '~/config/config'

// Custom MIME header carrying the full tracking code (including distinct_id + isTest, HMAC-signed).
// Used in place of the SES `EmailTags` carrier because tag values are capped at 256 chars,
// which a long distinct_id plus the signature blows past. Header values have no such limit.
export const TRACKING_CODE_HEADER_NAME = 'X-PostHog-Tracking-Code'

// HMAC tag truncated to 16 bytes (128 bits) — plenty against forgery, keeps the code short.
const SIGNATURE_BYTES = 16

export type TrackingCodeFormat = 'signed' | 'unsigned'

// Tracks the rollout curve from unsigned to signed tracking codes, split by where the
// code was read from (the public tracking endpoint vs. the SES webhook). After rollout
// completes, `format="unsigned"` from `source="tracking"` should trend to zero.
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
    // Accept a signature made with any configured key so key rotation doesn't invalidate
    // in-flight codes signed with the previous key.
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
    distinctId?: string
}

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

export const parseEmailTrackingCode = (encodedTrackingCode: string): ParsedTrackingCode | null => {
    if (!encodedTrackingCode) {
        return null
    }

    let payloadB64 = encodedTrackingCode
    let format: TrackingCodeFormat = 'unsigned'

    const parts = encodedTrackingCode.split('.')
    if (parts.length > 1) {
        // A legitimate signed code is exactly `<payload>.<signature>`; both halves are base64url
        // (no dots), so any code with more than one `.` is malformed and rejected outright.
        // A signed code with a bad signature is rejected — this is what stops URL forgery.
        if (parts.length !== 2 || !verifySignature(parts[0], parts[1])) {
            return null
        }
        payloadB64 = parts[0]
        format = 'signed'
    }

    try {
        const decoded = fromBase64UrlSafe(payloadB64)
        // Segments: functionId:invocationId:teamId:actionId:parentRunId:isTest:distinctId
        // isTest is a fixed single segment; distinctId is the trailing segment and may itself
        // contain colons, so anything past the 6th segment is rejoined. Older codes with fewer
        // segments resolve their missing trailing fields to undefined / isTest=false.
        const [functionId, invocationId, teamId, actionId, parentRunId, isTest, ...distinctIdParts] = decoded.split(':')
        if (!functionId || !invocationId) {
            return null
        }
        const distinctId = distinctIdParts.length > 0 ? distinctIdParts.join(':') : undefined
        return {
            functionId,
            invocationId,
            teamId,
            actionId: actionId || undefined,
            parentRunId: parentRunId || undefined,
            isTest: isTest === '1',
            distinctId: distinctId || undefined,
            format,
        }
    } catch {
        return null
    }
}

// Full tracking code: all fields (including distinct_id + isTest), HMAC-signed when a signing key is
// configured. This rides in the custom MIME header and the pixel/link URLs — carriers with no length
// cap — so a long distinct_id plus the signature is fine. The signature lets the public tracking
// endpoint reject forged `ph_id` values.
export const generateEmailTrackingCode = (invocation: TrackingInvocation, isTest = false): string => {
    const actionId = invocation.state?.actionId ?? ''
    const parentRunId = invocation.parentRunId ?? ''
    const distinctId = invocation.distinctId ?? ''
    // Segments: functionId:invocationId:teamId:actionId:parentRunId:isTest:distinctId.
    // isTest ('1' for "Run test" sends) lets the webhook skip their metrics; distinctId attributes
    // engagement events. distinctId is last because it may contain colons.
    const payload = toBase64UrlSafe(
        `${invocation.functionId}:${invocation.id}:${invocation.teamId}:${actionId}:${parentRunId}:${isTest ? '1' : ''}:${distinctId}`
    )
    const keys = getSigningKeys()
    if (keys.length === 0) {
        // Fail open while signing rolls out so sends never break; tighten to throw once enforced (#62624).
        return payload
    }
    return `${payload}.${signPayload(payload, keys[0])}`
}

// Bounded version of the tracking code: omits distinct_id and isTest and is never signed, so the
// value stays short and within the SES `EmailTags` 256-char cap regardless of distinct_id length.
// Used purely as a backwards-compat carrier in the SES tag; the authoritative signed code (with
// distinct_id + isTest) rides in the header (see TRACKING_CODE_HEADER_NAME). Do NOT sign this —
// the tag arrives via the SNS webhook, which is already integrity-protected by SNS signing.
export const generateShortEmailTrackingCode = (invocation: TrackingInvocation): string => {
    const actionId = invocation.state?.actionId ?? ''
    const parentRunId = invocation.parentRunId ?? ''
    return toBase64UrlSafe(`${invocation.functionId}:${invocation.id}:${invocation.teamId}:${actionId}:${parentRunId}`)
}

export const generateEmailTrackingPixelUrl = (invocation: TrackingInvocation, isTest = false): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/pixel?ph_id=${generateEmailTrackingCode(invocation, isTest)}`
}

import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { defaultConfig } from '~/config/config'

// Custom MIME header carrying the full tracking code (including distinct_id).
// Used in place of the SES `EmailTags` carrier because tag values are capped at
// 256 chars, which a distinct_id of even moderate length blows past.
export const TRACKING_CODE_HEADER_NAME = 'X-PostHog-Tracking-Code'

function toBase64UrlSafe(input: string) {
    // Encode to normal base64
    const b64 = Buffer.from(input, 'utf8').toString('base64')
    // Make URL safe and strip padding
    return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fromBase64UrlSafe(b64url: string) {
    // Restore base64 from URL-safe variant
    let b64 = b64url.replace(/-/g, '+').replace(/_/g, '/')
    // Pad to length multiple of 4
    while (b64.length % 4) {
        b64 += '='
    }
    return Buffer.from(b64, 'base64').toString('utf8')
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
    distinctId?: string
}

export const parseEmailTrackingCode = (encodedTrackingCode: string): ParsedTrackingCode | null => {
    const decodedTrackingCode = fromBase64UrlSafe(encodedTrackingCode)
    try {
        // Tracking codes evolved over time. Older codes may have fewer segments;
        // missing segments resolve to undefined. distinctId is the trailing segment
        // and may itself contain colons, so anything past the 5th segment is rejoined.
        const segments = decodedTrackingCode.split(':')
        const [functionId, invocationId, teamId, actionId, parentRunId, ...distinctIdParts] = segments
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
            distinctId: distinctId || undefined,
        }
    } catch {
        return null
    }
}

export const generateEmailTrackingCode = (invocation: TrackingInvocation): string => {
    // Generate a base64 encoded string free of equal signs
    const actionId = invocation.state?.actionId ?? ''
    const parentRunId = invocation.parentRunId ?? ''
    const distinctId = invocation.distinctId ?? ''
    return toBase64UrlSafe(
        `${invocation.functionId}:${invocation.id}:${invocation.teamId}:${actionId}:${parentRunId}:${distinctId}`
    )
}

// Bounded version of the tracking code, omitting distinct_id. Used as the SES
// `EmailTags` value (256-char cap, restricted charset) so the tag write never
// fails regardless of how long distinct_id is. The full code, with distinct_id,
// rides in a custom MIME header instead (see TRACKING_CODE_HEADER_NAME).
export const generateShortEmailTrackingCode = (invocation: TrackingInvocation): string => {
    const actionId = invocation.state?.actionId ?? ''
    const parentRunId = invocation.parentRunId ?? ''
    return toBase64UrlSafe(`${invocation.functionId}:${invocation.id}:${invocation.teamId}:${actionId}:${parentRunId}`)
}

export const generateEmailTrackingPixelUrl = (invocation: TrackingInvocation): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/pixel?ph_id=${generateEmailTrackingCode(invocation)}`
}

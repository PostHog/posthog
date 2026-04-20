import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { defaultConfig } from '~/config/config'

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

export const parseEmailTrackingCode = (
    encodedTrackingCode: string
): {
    functionId: string
    invocationId: string
    teamId: string
    actionId?: string
    parentRunId?: string
} | null => {
    const decodedTrackingCode = fromBase64UrlSafe(encodedTrackingCode)
    try {
        // 5-field format: functionId:invocationId:teamId:actionId:parentRunId
        // Old 4-field format (no parentRunId) still parses correctly.
        const [functionId, invocationId, teamId, actionId, parentRunId] = decodedTrackingCode.split(':')
        if (!functionId || !invocationId) {
            return null
        }
        return {
            functionId,
            invocationId,
            teamId,
            actionId: actionId || undefined,
            parentRunId: parentRunId || undefined,
        }
    } catch {
        return null
    }
}

export const generateEmailTrackingCode = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id' | 'teamId' | 'parentRunId'> & {
        state?: { actionId?: string }
    }
): string => {
    // Generate a base64 encoded string free of equal signs
    const actionId = invocation.state?.actionId ?? ''
    const parentRunId = invocation.parentRunId ?? ''
    return toBase64UrlSafe(`${invocation.functionId}:${invocation.id}:${invocation.teamId}:${actionId}:${parentRunId}`)
}

export const generateEmailTrackingPixelUrl = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id' | 'teamId' | 'parentRunId'> & {
        state?: { actionId?: string }
    }
): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/pixel?ph_id=${generateEmailTrackingCode(invocation)}`
}

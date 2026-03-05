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

export type ParsedTrackingCode = {
    functionId: string
    invocationId: string
    distinctId?: string
}

export const parseEmailTrackingCode = (encodedTrackingCode: string): ParsedTrackingCode | null => {
    const decodedTrackingCode = fromBase64UrlSafe(encodedTrackingCode)
    try {
        const [functionId, invocationId, ...distinctIdParts] = decodedTrackingCode.split(':')
        if (!functionId || !invocationId) {
            return null
        }
        // distinct_id may contain colons (e.g. email addresses don't, but UUIDs with custom formats might)
        const distinctId = distinctIdParts.length > 0 ? distinctIdParts.join(':') : undefined
        return { functionId, invocationId, distinctId: distinctId || undefined }
    } catch {
        return null
    }
}

export const generateEmailTrackingCode = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id'>,
    distinctId?: string
): string => {
    const parts = [invocation.functionId, invocation.id]
    if (distinctId) {
        parts.push(distinctId)
    }
    return toBase64UrlSafe(parts.join(':'))
}

export const generateEmailTrackingPixelUrl = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id'>,
    distinctId?: string
): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/pixel?ph_id=${generateEmailTrackingCode(invocation, distinctId)}`
}

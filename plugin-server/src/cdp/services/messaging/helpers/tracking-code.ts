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
): { functionId: string; invocationId: string } | null => {
    // customId  is like ph_fn_id=function-1&ph_inv_id=invocation-1
    const decodedTrackingCode = fromBase64UrlSafe(encodedTrackingCode)
    try {
        const [functionId, invocationId] = decodedTrackingCode.split(':')
        if (!functionId || !invocationId) {
            return null
        }
        return { functionId, invocationId }
    } catch {
        return null
    }
}

export const generateEmailTrackingCode = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id'>
): string => {
    // Generate a base64 encoded string free of equal signs
    return toBase64UrlSafe(`${invocation.functionId}:${invocation.id}`)
}

export const generateEmailTrackingPixelUrl = (
    invocation: Pick<CyclotronJobInvocationHogFunction, 'functionId' | 'id'>
): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/pixel?ph_id=${generateEmailTrackingCode(invocation)}`
}

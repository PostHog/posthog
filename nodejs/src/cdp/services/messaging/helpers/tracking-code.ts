import crypto from 'node:crypto'
import { Counter } from 'prom-client'

import { CyclotronJobInvocationHogFunction } from '~/cdp/types'
import { defaultConfig } from '~/config/config'

const SIGNATURE_BYTES = 16

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
    return (defaultConfig.ENCRYPTION_SALT_KEYS || '').split(',').filter(Boolean)
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
        if (candidate.length === expected.length && crypto.timingSafeEqual(expected, candidate)) {
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
    format: TrackingCodeFormat
} | null => {
    if (!encodedTrackingCode) {
        return null
    }

    let payloadB64 = encodedTrackingCode
    let format: TrackingCodeFormat = 'unsigned'

    const [payload, signature] = encodedTrackingCode.split('.')
    if (signature !== undefined) {
        if (!verifySignature(payload, signature)) {
            return null
        }
        payloadB64 = payload
        format = 'signed'
    }

    try {
        const decoded = fromBase64UrlSafe(payloadB64)
        const [functionId, invocationId, teamId, actionId, parentRunId] = decoded.split(':')
        if (!functionId || !invocationId) {
            return null
        }
        return {
            functionId,
            invocationId,
            teamId,
            actionId: actionId || undefined,
            parentRunId: parentRunId || undefined,
            format,
        }
    } catch {
        return null
    }
}

export const generateEmailTrackingCode = (invocation: TrackingInvocation): string => {
    const actionId = invocation.state?.actionId ?? ''
    const parentRunId = invocation.parentRunId ?? ''
    const payload = toBase64UrlSafe(
        `${invocation.functionId}:${invocation.id}:${invocation.teamId}:${actionId}:${parentRunId}`
    )
    const keys = getSigningKeys()
    if (keys.length === 0) {
        return payload
    }
    return `${payload}.${signPayload(payload, keys[0])}`
}

export const generateEmailTrackingPixelUrl = (invocation: TrackingInvocation): string => {
    return `${defaultConfig.CDP_EMAIL_TRACKING_URL}/public/m/pixel?ph_id=${generateEmailTrackingCode(invocation)}`
}

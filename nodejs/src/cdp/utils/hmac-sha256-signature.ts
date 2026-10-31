import { createHmac } from 'node:crypto'

import { CyclotronInvocationQueueParametersFetchHmacSha256Type } from '~/cdp/schema/cyclotron'

import { HogFunctionType } from '../types'
import { resolveHogFunctionInputValue } from './hog-function-inputs'

const SIGNATURE_HEADER = 'x-hub-signature-256'
const DELIVERY_ID_HEADER = 'webhook-id'
const SIGNING_HEADERS = new Set([SIGNATURE_HEADER, DELIVERY_ID_HEADER])

export type ResolvedHmacSha256Secret = { ok: true; secret: string } | { ok: false; error: string }

export type SignHmacSha256RequestArgs = {
    webhookId: string
    body?: string | null
    headers?: Record<string, string>
    secret: string
}

export function resolveHmacSha256Secret(
    params: Pick<CyclotronInvocationQueueParametersFetchHmacSha256Type, 'secret_input'>,
    hogFunction: Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'>
): ResolvedHmacSha256Secret {
    const secret = resolveHogFunctionInputValue(hogFunction, params.secret_input)

    if (typeof secret !== 'string' || secret.length === 0) {
        return {
            ok: false,
            error: `HMAC-SHA256 signing failed: input ${params.secret_input} not found on hog function or not a string. Refusing to send an unsigned request.`,
        }
    }

    return { ok: true, secret }
}

export function signHmacSha256Request({
    webhookId,
    body,
    headers,
    secret,
}: SignHmacSha256RequestArgs): Record<string, string> {
    const signature = createHmac('sha256', secret)
        .update(body ?? '')
        .digest('hex')

    const outHeaders: Record<string, string> = {}
    for (const [headerKey, headerValue] of Object.entries(headers ?? {})) {
        if (!SIGNING_HEADERS.has(headerKey.toLowerCase())) {
            outHeaders[headerKey] = headerValue
        }
    }

    return {
        ...outHeaders,
        [DELIVERY_ID_HEADER]: webhookId,
        [SIGNATURE_HEADER]: `sha256=${signature}`,
    }
}

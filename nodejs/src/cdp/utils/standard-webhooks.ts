import { createHmac } from 'node:crypto'

import { CyclotronInvocationQueueParametersFetchStandardWebhooksType } from '~/cdp/schema/cyclotron'

import { HogFunctionType } from '../types'
import { resolveHogFunctionInputValue } from './hog-function-inputs'

// Headers that are signing artifacts. They must always be rebuilt, never
// inherited from a previous attempt's queue payload.
const SIGNING_HEADERS = new Set(['webhook-id', 'webhook-timestamp', 'webhook-signature'])

// Standard Webhooks secrets are base64, optionally prefixed with "whsec_".
// See https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md
const BASE64_SECRET_REGEX = /^[A-Za-z0-9+/]+={0,2}$/

// The spec puts symmetric signing secrets at 24 bytes or more. Shorter almost
// always means a truncated paste, and base64 decoding is lenient enough to turn
// one into a short or even empty HMAC key, which anyone could reproduce. Fail
// here so the customer sees the cause instead of a 403 from the receiver. There
// is deliberately no upper bound: HMAC-SHA256 folds a long key down itself, so
// rejecting one would only break a receiver that issues them.
const MIN_SECRET_KEY_BYTES = 24

export type ResolvedStandardWebhooksKey = { ok: true; key: Buffer } | { ok: false; error: string }

export type SignStandardWebhooksRequestArgs = {
    webhookId: string
    body?: string | null
    headers?: Record<string, string>
    key: Buffer
    now?: Date
}

export function resolveStandardWebhooksKey(
    params: Pick<CyclotronInvocationQueueParametersFetchStandardWebhooksType, 'secret_input'>,
    hogFunction: Pick<HogFunctionType, 'inputs' | 'encrypted_inputs'>
): ResolvedStandardWebhooksKey {
    const secret = resolveHogFunctionInputValue(hogFunction, params.secret_input)

    if (typeof secret !== 'string' || secret.length === 0) {
        return {
            ok: false,
            error: `Standard Webhooks signing failed: input ${params.secret_input} not found on hog function or not a string. Refusing to send an unsigned request.`,
        }
    }

    const encoded = secret.startsWith('whsec_') ? secret.slice('whsec_'.length) : secret

    if (!BASE64_SECRET_REGEX.test(encoded)) {
        return {
            ok: false,
            error: `Standard Webhooks signing failed: the signing secret is not valid base64. Provide the secret exactly as issued, with or without the whsec_ prefix.`,
        }
    }

    const key = Buffer.from(encoded, 'base64')

    if (key.length < MIN_SECRET_KEY_BYTES) {
        return {
            ok: false,
            error: `Standard Webhooks signing failed: the signing secret decodes to ${key.length} bytes, but the spec requires at least ${MIN_SECRET_KEY_BYTES}. Check that the whole secret was pasted.`,
        }
    }

    return { ok: true, key }
}

/**
 * Signs an HTTP request per the Standard Webhooks spec: HMAC-SHA256 over
 * `${webhook-id}.${webhook-timestamp}.${body}` with the base64-decoded secret,
 * sent as `webhook-signature: v1,<base64 digest>`.
 *
 * Returns a fresh headers object that callers should USE INSTEAD OF any prior
 * `webhook-*` headers: those are signing artifacts, and a stale timestamp
 * fails the receiver's tolerance check (5 minutes in the reference
 * implementations), so this must be called immediately before each fetch
 * attempt. `webhookId` deliberately stays the caller's job: the spec wants it
 * constant across retries (receivers use it for idempotency) while the
 * timestamp and signature must be fresh.
 */
export function signStandardWebhooksRequest({
    webhookId,
    body,
    headers,
    key,
    now,
}: SignStandardWebhooksRequestArgs): Record<string, string> {
    // Defaults to `Date.now()` so jest's `Date.now` mock (the standard PostHog
    // test seam) flows through to the signature timestamp.
    const timestamp = String(Math.floor((now?.getTime() ?? Date.now()) / 1000))
    const signature = createHmac('sha256', key)
        .update(`${webhookId}.${timestamp}.${body ?? ''}`)
        .digest('base64')

    const outHeaders: Record<string, string> = {}
    for (const [headerKey, headerValue] of Object.entries(headers ?? {})) {
        if (!SIGNING_HEADERS.has(headerKey.toLowerCase())) {
            outHeaders[headerKey] = headerValue
        }
    }

    return {
        ...outHeaders,
        'webhook-id': webhookId,
        'webhook-timestamp': timestamp,
        'webhook-signature': `v1,${signature}`,
    }
}

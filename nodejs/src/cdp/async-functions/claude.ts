import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

// Anthropic Managed Agents API — see https://platform.claude.com/docs/en/managed-agents/sessions
//
// Two-step flow:
//   1. POST /v1/sessions                 — create session (agent + environment_id [+ vault_ids])
//   2. POST /v1/sessions/{id}/events     — send a user.message event to drive execution
//   3. POST /v1/sessions/{id}/cancel     — best-effort cancel for orphan cleanup
//
// The hog template chains them:
//   let session := claudeCreateSession({...})
//   claudeSendUserMessage({api_key, session_id: session.body.id, text: inputs.message})
//
// IMPORTANT: `ANTHROPIC_BETA_HEADER` must stay in sync with
// `ANTHROPIC_MANAGED_AGENTS_BETA_HEADER` in `posthog/models/integration.py` —
// see `claude.test.ts` for the parity check.
export const ANTHROPIC_BETA_HEADER = 'managed-agents-2026-04-01'
const DEFAULT_ANTHROPIC_API_BASE_URL = 'https://api.anthropic.com'
// 1 MiB cap on the user message: cyclotron persists request bodies through Postgres
// and Kafka before the fetch fires, so a multi-MiB Liquid-rendered message is paid
// for upstream of any Anthropic-side rejection.
const MAX_USER_MESSAGE_BYTES = 1_000_000
// Anthropic session ids are opaque but follow a `prefix_alphanum` shape; a tight
// regex guards against path-traversal-ish values surviving encodeURIComponent.
const SESSION_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/

function getSessionsBaseUrl(): string {
    return `${process.env.ANTHROPIC_API_BASE_URL ?? DEFAULT_ANTHROPIC_API_BASE_URL}/v1/sessions`
}

function commonHeaders(apiKey: string, idempotencyKey?: string): Record<string, string> {
    const headers: Record<string, string> = {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-beta': ANTHROPIC_BETA_HEADER,
        'Content-Type': 'application/json',
    }
    if (idempotencyKey) {
        headers['Idempotency-Key'] = idempotencyKey
    }
    return headers
}

function redactedArgs(args: any[]): any[] {
    return args.map((arg) => {
        if (arg && typeof arg === 'object' && 'api_key' in arg) {
            return { ...arg, api_key: '[redacted]' }
        }
        return arg
    })
}

registerAsyncFunction('claudeCreateSession', {
    execute: (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const apiKey = opts?.api_key
        const agent = opts?.agent
        const environmentId = opts?.environment_id
        const vaultIds = opts?.vault_ids

        if (!apiKey || typeof apiKey !== 'string') {
            throw new Error("[HogFunction] - claudeCreateSession call missing 'api_key'")
        }
        if (!agent || typeof agent !== 'string') {
            throw new Error("[HogFunction] - claudeCreateSession call missing 'agent'")
        }
        if (!environmentId || typeof environmentId !== 'string') {
            throw new Error("[HogFunction] - claudeCreateSession call missing 'environment_id'")
        }

        const body: Record<string, unknown> = {
            agent,
            environment_id: environmentId,
        }
        if (Array.isArray(vaultIds)) {
            const cleaned = vaultIds.filter((v): v is string => typeof v === 'string' && v.length > 0)
            if (cleaned.length > 0) {
                body.vault_ids = cleaned
            }
        }

        // Idempotency-Key uses the cyclotron invocation id so cyclotron-level
        // re-enqueues, worker crashes, and the inner connection-error retry in
        // cdpTrackedFetch all hit the same server-side dedupe slot.
        // max_tries: 1 caps the retriable-status retry loop because POST creating
        // a session is non-idempotent if Anthropic hasn't honored the key yet.
        const idempotencyKey = `${context.invocation.id}:claudeCreateSession`

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: getSessionsBaseUrl(),
            method: 'POST',
            headers: commonHeaders(apiKey, idempotencyKey),
            body: JSON.stringify(body),
            max_tries: 1,
        })
    },

    mock: (args, logs) => {
        const [opts] = (args as [Record<string, any> | undefined]) ?? [{}]
        const overrideStatus = typeof opts?.__mock_status === 'number' ? opts.__mock_status : 200
        const overrideBody = opts?.__mock_body
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'claudeCreateSession' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `claudeCreateSession(${JSON.stringify(redactedArgs(args)[0], null, 2)})`,
        })
        return {
            status: overrideStatus,
            body: overrideBody ?? {
                id: 'mock-session-id',
                status: 'idle',
                environment_id: opts?.environment_id ?? 'mock-env',
                agent: opts?.agent ?? 'mock-agent',
            },
        }
    },
})

registerAsyncFunction('claudeSendUserMessage', {
    execute: (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const apiKey = opts?.api_key
        const sessionId = opts?.session_id
        const text = opts?.text

        if (!apiKey || typeof apiKey !== 'string') {
            throw new Error("[HogFunction] - claudeSendUserMessage call missing 'api_key'")
        }
        if (!sessionId || typeof sessionId !== 'string') {
            throw new Error("[HogFunction] - claudeSendUserMessage call missing 'session_id'")
        }
        if (!SESSION_ID_PATTERN.test(sessionId)) {
            throw new Error("[HogFunction] - claudeSendUserMessage call has malformed 'session_id'")
        }
        if (typeof text !== 'string' || text.length === 0) {
            throw new Error("[HogFunction] - claudeSendUserMessage call missing 'text' (must be a non-empty string)")
        }
        if (Buffer.byteLength(text, 'utf8') > MAX_USER_MESSAGE_BYTES) {
            throw new Error(`[HogFunction] - claudeSendUserMessage 'text' exceeds ${MAX_USER_MESSAGE_BYTES} bytes`)
        }

        const body = {
            events: [
                {
                    type: 'user.message',
                    content: [{ type: 'text', text }],
                },
            ],
        }

        const idempotencyKey = `${context.invocation.id}:claudeSendUserMessage:${sessionId}`

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${getSessionsBaseUrl()}/${encodeURIComponent(sessionId)}/events`,
            method: 'POST',
            headers: commonHeaders(apiKey, idempotencyKey),
            body: JSON.stringify(body),
            max_tries: 1,
        })
    },

    mock: (args, logs) => {
        const [opts] = (args as [Record<string, any> | undefined]) ?? [{}]
        const overrideStatus = typeof opts?.__mock_status === 'number' ? opts.__mock_status : 200
        const overrideBody = opts?.__mock_body
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'claudeSendUserMessage' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `claudeSendUserMessage(${JSON.stringify(redactedArgs(args)[0], null, 2)})`,
        })
        return { status: overrideStatus, body: overrideBody ?? { ok: true } }
    },
})

// Best-effort cancel of an orphaned session — used by the template when message
// send fails after session create. We intentionally do not throw on cancel
// failure; the surrounding hog code already throws on the original failure and
// the cancel is a recovery attempt that should not mask the real error.
registerAsyncFunction('claudeCancelSession', {
    execute: (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const apiKey = opts?.api_key
        const sessionId = opts?.session_id

        if (!apiKey || typeof apiKey !== 'string') {
            throw new Error("[HogFunction] - claudeCancelSession call missing 'api_key'")
        }
        if (!sessionId || typeof sessionId !== 'string') {
            throw new Error("[HogFunction] - claudeCancelSession call missing 'session_id'")
        }
        if (!SESSION_ID_PATTERN.test(sessionId)) {
            throw new Error("[HogFunction] - claudeCancelSession call has malformed 'session_id'")
        }

        const idempotencyKey = `${context.invocation.id}:claudeCancelSession:${sessionId}`

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${getSessionsBaseUrl()}/${encodeURIComponent(sessionId)}/cancel`,
            method: 'POST',
            headers: commonHeaders(apiKey, idempotencyKey),
            body: JSON.stringify({}),
            max_tries: 1,
        })
    },

    mock: (args, logs) => {
        const [opts] = (args as [Record<string, any> | undefined]) ?? [{}]
        const overrideStatus = typeof opts?.__mock_status === 'number' ? opts.__mock_status : 200
        const overrideBody = opts?.__mock_body
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'claudeCancelSession' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `claudeCancelSession(${JSON.stringify(redactedArgs(args)[0], null, 2)})`,
        })
        return { status: overrideStatus, body: overrideBody ?? { ok: true } }
    },
})

import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

// Anthropic Managed Agents API — see https://platform.claude.com/docs/en/managed-agents/sessions
// All requests need the managed-agents-2026-04-01 beta header.
//
// Two-step flow:
//   1. POST /v1/sessions                 — create session (agent + environment_id [+ vault_ids])
//   2. POST /v1/sessions/{id}/events     — send a user.message event to drive execution
//
// We split this into two async functions so the hog template can chain them:
//   let session := claudeCreateSession({...})
//   claudeSendUserMessage({api_key, session_id: session.body.id, text: inputs.message})
const ANTHROPIC_BETA_HEADER = 'managed-agents-2026-04-01'
const ANTHROPIC_SESSIONS_URL = 'https://api.anthropic.com/v1/sessions'

function commonHeaders(apiKey: string): Record<string, string> {
    return {
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-beta': ANTHROPIC_BETA_HEADER,
        'Content-Type': 'application/json',
    }
}

registerAsyncFunction('claudeCreateSession', {
    execute: (args, _context, result) => {
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
        if (Array.isArray(vaultIds) && vaultIds.length > 0) {
            body.vault_ids = vaultIds
        } else if (typeof vaultIds === 'string' && vaultIds.length > 0) {
            body.vault_ids = [vaultIds]
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: ANTHROPIC_SESSIONS_URL,
            method: 'POST',
            headers: commonHeaders(apiKey),
            body: JSON.stringify(body),
        })
    },

    mock: (args, logs) => {
        const [opts] = (args as [Record<string, any> | undefined]) ?? [{}]
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'claudeCreateSession' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `claudeCreateSession(${JSON.stringify(args[0], null, 2)})`,
        })
        return {
            status: 200,
            body: {
                id: 'mock-session-id',
                status: 'idle',
                environment_id: opts?.environment_id ?? 'mock-env',
                agent: opts?.agent ?? 'mock-agent',
            },
        }
    },
})

registerAsyncFunction('claudeSendUserMessage', {
    execute: (args, _context, result) => {
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
        if (!text || typeof text !== 'string') {
            throw new Error("[HogFunction] - claudeSendUserMessage call missing 'text'")
        }

        const body = {
            events: [
                {
                    type: 'user.message',
                    content: [{ type: 'text', text }],
                },
            ],
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${ANTHROPIC_SESSIONS_URL}/${encodeURIComponent(sessionId)}/events`,
            method: 'POST',
            headers: commonHeaders(apiKey),
            body: JSON.stringify(body),
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'claudeSendUserMessage' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `claudeSendUserMessage(${JSON.stringify(args[0], null, 2)})`,
        })
        return { status: 200, body: { ok: true } }
    },
})

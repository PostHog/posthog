import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

const ANTHROPIC_BETA_HEADER = 'managed-agents-2026-04-01'
const ANTHROPIC_SESSIONS_URL = 'https://api.anthropic.com/v1/sessions'

registerAsyncFunction('claudeCreateSession', {
    execute: (args, _context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const apiKey = opts?.api_key
        const agent = opts?.agent
        const environmentId = opts?.environment_id
        const vaultIds = opts?.vault_ids
        const message = opts?.message

        if (!apiKey || typeof apiKey !== 'string') {
            throw new Error("[HogFunction] - claudeCreateSession call missing 'api_key'")
        }
        if (!agent || typeof agent !== 'string') {
            throw new Error("[HogFunction] - claudeCreateSession call missing 'agent'")
        }
        if (!environmentId || typeof environmentId !== 'string') {
            throw new Error("[HogFunction] - claudeCreateSession call missing 'environment_id'")
        }
        if (!message || typeof message !== 'string') {
            throw new Error("[HogFunction] - claudeCreateSession call missing 'message'")
        }

        const body: Record<string, unknown> = {
            agent,
            environment_id: environmentId,
            initial_message: message,
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
            headers: {
                'x-api-key': apiKey,
                'anthropic-version': '2023-06-01',
                'anthropic-beta': ANTHROPIC_BETA_HEADER,
                'Content-Type': 'application/json',
            },
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
                status: 'queued',
                environment_id: opts?.environment_id ?? 'mock-env',
                agent: opts?.agent ?? 'mock-agent',
            },
        }
    },
})

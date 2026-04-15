import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('postHogLLMCompletion', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]

        if (!opts?.provider_key_id || typeof opts.provider_key_id !== 'string') {
            throw new Error("[HogFunction] - postHogLLMCompletion call missing 'provider_key_id' property")
        }
        if (!opts?.provider || typeof opts.provider !== 'string') {
            throw new Error("[HogFunction] - postHogLLMCompletion call missing 'provider' property")
        }
        if (!opts?.model || typeof opts.model !== 'string') {
            throw new Error("[HogFunction] - postHogLLMCompletion call missing 'model' property")
        }
        if (!Array.isArray(opts?.messages) || opts.messages.length === 0) {
            throw new Error("[HogFunction] - postHogLLMCompletion call missing 'messages' property")
        }

        const team = await context.teamManager.getTeam(context.invocation.teamId)
        if (!team) {
            throw new Error(`Team ${context.invocation.teamId} not found`)
        }
        if (!team.secret_api_token) {
            throw new Error(`Team ${context.invocation.teamId} has no secret API token configured`)
        }

        const body: Record<string, any> = {
            provider_key_id: opts.provider_key_id,
            provider: opts.provider,
            model: opts.model,
            messages: opts.messages,
        }

        if (opts.system) {
            body.system = opts.system
        }
        if (opts.temperature !== undefined && opts.temperature !== null) {
            body.temperature = opts.temperature
        }
        if (opts.max_tokens !== undefined && opts.max_tokens !== null) {
            body.max_tokens = opts.max_tokens
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/llm/workflow/completion`,
            method: 'POST',
            body: JSON.stringify(body),
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${team.secret_api_token}`,
            },
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogLLMCompletion' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogLLMCompletion(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 200,
            body: {
                content: 'This is a mock LLM response for testing.',
                model: args[0]?.model ?? 'mock-model',
                usage: {
                    input_tokens: 10,
                    output_tokens: 20,
                },
            },
        }
    },
})

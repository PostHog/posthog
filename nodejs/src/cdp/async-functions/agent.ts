import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('postHogRunAgent', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const prompt = opts?.prompt

        if (!prompt || typeof prompt !== 'string') {
            throw new Error("[HogFunction] - postHogRunAgent call missing 'prompt' property")
        }

        const team = await context.teamManager.getTeam(context.invocation.teamId)
        if (!team) {
            throw new Error(`Team ${context.invocation.teamId} not found`)
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/agent/run`,
            method: 'POST',
            body: JSON.stringify({
                message: prompt,
                repository: opts?.repository ?? null,
                output_schema: opts?.output_schema ?? null,
            }),
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${team.api_token}`,
            },
            timeout_ms: 660_000, // 11 minutes — agent runs can take several minutes
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogRunAgent' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogRunAgent(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 200,
            body: {
                status: 'completed',
                output: { result: 'mock agent result' },
            },
        }
    },
})

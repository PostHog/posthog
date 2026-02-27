import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('postHogQuery', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const query = opts?.query

        if (!query || typeof query !== 'string') {
            throw new Error("[HogFunction] - postHogQuery call missing 'query' property")
        }

        const team = await context.teamManager.getTeam(context.invocation.teamId)
        if (!team) {
            throw new Error(`Team ${context.invocation.teamId} not found`)
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/environments/${context.invocation.teamId}/query/`,
            method: 'POST',
            body: JSON.stringify({ query: { kind: 'HogQLQuery', query } }),
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${team.api_token}`,
            },
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogQuery' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogQuery(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 200,
            body: {
                columns: ['event', 'count'],
                results: [
                    ['pageview', 1000],
                    ['$autocapture', 500],
                    ['$identify', 250],
                ],
                hasMore: false,
                hogql: args[0]?.query ?? '',
            },
        }
    },
})

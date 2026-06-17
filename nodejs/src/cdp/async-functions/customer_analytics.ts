import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/schema/cyclotron'

import { registerAsyncFunction } from '../async-function-registry'

registerAsyncFunction('postHogGetAccount', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const externalId = opts?.external_id

        if (!externalId || typeof externalId !== 'string') {
            throw new Error("[HogFunction] - postHogGetAccount call missing 'external_id' property")
        }

        const team = await context.teamManager.getTeam(context.invocation.teamId)
        if (!team) {
            throw new Error(`Team ${context.invocation.teamId} not found`)
        }
        if (!team.secret_api_token) {
            throw new Error(`Team ${context.invocation.teamId} has no secret API token configured`)
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/customer_analytics/external/account?external_id=${encodeURIComponent(
                externalId
            )}`,
            method: 'GET',
            headers: { Authorization: `Bearer ${team.secret_api_token}` },
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogGetAccount' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogGetAccount(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 200,
            body: {
                id: 'mock-account-id',
                external_id: args[0]?.external_id ?? 'mock-external-id',
                name: 'Mock Account',
                properties: {
                    csm: null,
                    account_executive: null,
                    account_owner: null,
                    stripe_customer_id: null,
                    hubspot_deal_id: null,
                    billing_id: null,
                    sfdc_id: null,
                    zendesk_id: null,
                    slack_channel_id: null,
                    usage_dashboard_link: null,
                },
            },
        }
    },
})

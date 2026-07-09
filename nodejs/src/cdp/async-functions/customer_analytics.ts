import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'
import { captureException } from '~/common/utils/posthog'
import { Team } from '~/types'

import { AsyncFunctionContext, registerAsyncFunction } from '../async-function-registry'

async function getTeamWithSecretToken(context: AsyncFunctionContext, functionName: string): Promise<Team> {
    const team = await context.teamManager.getTeam(context.invocation.teamId)
    if (!team) {
        throw new Error(`Team ${context.invocation.teamId} not found`)
    }
    if (!team.secret_api_token) {
        const error = new Error(`Team ${context.invocation.teamId} has no secret API token configured`)
        captureException(error, {
            tags: {
                team_id: context.invocation.teamId,
                function: functionName,
                template_id: context.invocation.hogFunction.template_id ?? null,
            },
        })
        throw error
    }
    return team
}

registerAsyncFunction('postHogGetAccount', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const externalId = opts?.external_id

        if (!externalId || typeof externalId !== 'string') {
            throw new Error("[HogFunction] - postHogGetAccount call missing 'external_id' property")
        }

        const team = await getTeamWithSecretToken(context, 'postHogGetAccount')

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/customer_analytics/external/account?external_id=${encodeURIComponent(externalId)}`,
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
                    stripe_customer_id: 'cus_mock',
                    hubspot_deal_id: 'deal_mock',
                    billing_id: 'bill_mock',
                    sfdc_id: 'sfdc_mock',
                    zendesk_id: 'zd_mock',
                    slack_channel_id: 'C0MOCK',
                    usage_dashboard_link: 'https://example.com/dashboard',
                },
                relationships: {
                    CSM: [{ user_id: 1, email: 'csm@example.com' }],
                    'Account executive': [{ user_id: 2, email: 'ae@example.com' }],
                },
            },
        }
    },
})

registerAsyncFunction('postHogUpdateAccount', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const externalId = opts?.external_id
        const updates = opts?.updates || {}

        if (!externalId || typeof externalId !== 'string') {
            throw new Error("[HogFunction] - postHogUpdateAccount call missing 'external_id' property")
        }

        const team = await getTeamWithSecretToken(context, 'postHogUpdateAccount')

        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${team.secret_api_token}`,
        }

        const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
        if (hogFlow?.id) {
            headers['X-PostHog-Hog-Flow-Id'] = hogFlow.id
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/customer_analytics/external/account`,
            method: 'PATCH',
            body: JSON.stringify({ external_id: externalId, ...updates }),
            headers,
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogUpdateAccount' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogUpdateAccount(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 200,
            body: { ok: true },
        }
    },
})

registerAsyncFunction('postHogSetAccountProperties', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const externalId = opts?.external_id
        const properties = opts?.properties || {}

        if (!externalId || typeof externalId !== 'string') {
            throw new Error("[HogFunction] - postHogSetAccountProperties call missing 'external_id' property")
        }

        const team = await getTeamWithSecretToken(context, 'postHogSetAccountProperties')

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/customer_analytics/external/account/custom_property_values`,
            method: 'PATCH',
            body: JSON.stringify({ external_id: externalId, properties }),
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
            message: `Async function 'postHogSetAccountProperties' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogSetAccountProperties(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 200,
            body: { ok: true },
        }
    },
})

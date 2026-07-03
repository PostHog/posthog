import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'

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
                    csm: { id: 1, email: 'csm@example.com' },
                    account_executive: { id: 2, email: 'ae@example.com' },
                    account_owner: { id: 3, email: 'owner@example.com' },
                    stripe_customer_id: 'cus_mock',
                    hubspot_deal_id: 'deal_mock',
                    billing_id: 'bill_mock',
                    sfdc_id: 'sfdc_mock',
                    zendesk_id: 'zd_mock',
                    slack_channel_id: 'C0MOCK',
                    usage_dashboard_link: 'https://example.com/dashboard',
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

        const team = await context.teamManager.getTeam(context.invocation.teamId)
        if (!team) {
            throw new Error(`Team ${context.invocation.teamId} not found`)
        }
        if (!team.secret_api_token) {
            throw new Error(`Team ${context.invocation.teamId} has no secret API token configured`)
        }

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/customer_analytics/external/account`,
            method: 'PATCH',
            body: JSON.stringify({ external_id: externalId, ...updates }),
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

        const team = await context.teamManager.getTeam(context.invocation.teamId)
        if (!team) {
            throw new Error(`Team ${context.invocation.teamId} not found`)
        }
        if (!team.secret_api_token) {
            throw new Error(`Team ${context.invocation.teamId} has no secret API token configured`)
        }

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

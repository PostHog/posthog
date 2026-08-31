import { DateTime } from 'luxon'

import { CyclotronInvocationQueueParametersFetchSchema } from '~/cdp/schema/cyclotron'
import { HogFlow } from '~/cdp/schema/hogflow'

import { AsyncFunctionContext, registerAsyncFunction } from '../async-function-registry'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { callInternalApi } from './internal-api-call'
import { getTeamWithSecretToken } from './secret-api-token'

const ACCOUNT_ACTIONS = 'account workflow actions'

/**
 * Calls the JWT-only internal account routes (products/customer_analytics/backend/
 * presentation/views/internal.py). The token pins the invocation's own team plus this one
 * account's external_id; Django refuses it anywhere else. Used whenever
 * CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRET is provisioned — the legacy secret_api_token path
 * below it is the fallback until then (#82564).
 */
async function callInternalAccountApi(
    context: AsyncFunctionContext,
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
    externalId: string,
    options: {
        method: 'GET' | 'PATCH' | 'POST'
        subpath?: string
        body?: string
        extraHeaders?: Record<string, string>
    }
): Promise<void> {
    const { method, subpath = '', body, extraHeaders } = options
    // The external_id is Hog-controlled free text. It travels in the query string (GET) or
    // the JSON body, never a URL path segment, so no format constraint applies — the claim
    // just has to carry the same raw value Django reads from the request.
    const base = `/api/projects/${context.invocation.teamId}/internal/customer_analytics/account${subpath}` as const
    const path = method === 'GET' ? `${base}?external_id=${encodeURIComponent(externalId)}` : base
    await callInternalApi(context, result, {
        jwt: context.customerAnalyticsAccountsJwt,
        path: path as `/${string}`,
        entityClaims: { external_id: externalId },
        method,
        body,
        extraHeaders,
    })
}

// Present only when running inside a HogFlow (spread onto the synthesized invocation);
// forwarded so account activity can attribute writes to the workflow. Only the id is sent —
// the display name is resolved from the workflow on the frontend so it can't be spoofed
// through this header. Typed as an optional HogFlow so a rename of its id shape breaks
// compilation here.
function hogFlowHeaders(context: AsyncFunctionContext): Record<string, string> {
    const hogFlow = (context.invocation as { hogFlow?: HogFlow }).hogFlow
    return hogFlow?.id ? { 'X-PostHog-Hog-Flow-Id': hogFlow.id } : {}
}

registerAsyncFunction('postHogGetAccount', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const externalId = opts?.external_id

        if (!externalId || typeof externalId !== 'string') {
            throw new Error("[HogFunction] - postHogGetAccount call missing 'external_id' property")
        }

        if (context.customerAnalyticsAccountsJwt.enabled) {
            // No team fetch and no secret_api_token requirement: teams that never minted the
            // legacy key can use account actions once the JWT secret is provisioned.
            await callInternalAccountApi(context, result, externalId, { method: 'GET' })
            return
        }

        const team = await getTeamWithSecretToken(context, 'postHogGetAccount', ACCOUNT_ACTIONS)

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
                custom_properties: {
                    Plan: 'enterprise',
                    'MRR (net)': 1234,
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

        if (context.customerAnalyticsAccountsJwt.enabled) {
            // external_id spreads last so no updates value can differ from the token's claim —
            // Django rejects a body whose external_id does not match the claim.
            await callInternalAccountApi(context, result, externalId, {
                method: 'PATCH',
                body: JSON.stringify({ ...updates, external_id: externalId }),
                extraHeaders: hogFlowHeaders(context),
            })
            return
        }

        const team = await getTeamWithSecretToken(context, 'postHogUpdateAccount', ACCOUNT_ACTIONS)

        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${team.secret_api_token}`,
        }

        Object.assign(headers, hogFlowHeaders(context))

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

        if (context.customerAnalyticsAccountsJwt.enabled) {
            await callInternalAccountApi(context, result, externalId, {
                method: 'PATCH',
                subpath: '/custom_property_values',
                body: JSON.stringify({ external_id: externalId, properties }),
                extraHeaders: hogFlowHeaders(context),
            })
            return
        }

        const team = await getTeamWithSecretToken(context, 'postHogSetAccountProperties', ACCOUNT_ACTIONS)

        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${team.secret_api_token}`,
        }

        Object.assign(headers, hogFlowHeaders(context))

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/customer_analytics/external/account/custom_property_values`,
            method: 'PATCH',
            body: JSON.stringify({ external_id: externalId, properties }),
            headers,
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

registerAsyncFunction('postHogCreateAccount', {
    execute: async (args, context, result) => {
        const [opts] = args as [Record<string, any> | undefined]
        const externalId = opts?.external_id

        if (!externalId || typeof externalId !== 'string') {
            throw new Error("[HogFunction] - postHogCreateAccount call missing 'external_id' property")
        }

        if (context.customerAnalyticsAccountsJwt.enabled) {
            await callInternalAccountApi(context, result, externalId, {
                method: 'POST',
                body: JSON.stringify({ external_id: externalId }),
                extraHeaders: hogFlowHeaders(context),
            })
            return
        }

        const team = await getTeamWithSecretToken(context, 'postHogCreateAccount', ACCOUNT_ACTIONS)

        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${team.secret_api_token}`,
        }

        Object.assign(headers, hogFlowHeaders(context))

        result.invocation.queueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
            type: 'fetch',
            url: `${context.siteUrl}/api/customer_analytics/external/account`,
            method: 'POST',
            body: JSON.stringify({ external_id: externalId }),
            headers,
        })
    },

    mock: (args, logs) => {
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Async function 'postHogCreateAccount' was mocked with arguments:`,
        })
        logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `postHogCreateAccount(${JSON.stringify(args[0], null, 2)})`,
        })

        return {
            status: 201,
            body: {
                id: 'mock-account-id',
                external_id: args[0]?.external_id ?? 'mock-external-id',
                name: 'Mock Account',
                properties: {},
                tags: [],
                relationships: {},
                custom_properties: {},
            },
        }
    },
})

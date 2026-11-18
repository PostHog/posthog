import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'

import { AsyncFunctionContext, registerAsyncFunction } from '../async-function-registry'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { callInternalApi } from './internal-api-call'

const ACCOUNT_ACTIONS = 'account workflow actions'
const CLEAR_PROPERTY_MARKER = '__posthog_clear_property'

function isClearPropertyMarker(value: unknown): boolean {
    return (
        typeof value === 'object' &&
        value !== null &&
        !Array.isArray(value) &&
        Object.keys(value).length === 1 &&
        (value as Record<string, unknown>)[CLEAR_PROPERTY_MARKER] === true
    )
}

function normalizeAccountProperties(properties: Record<string, unknown>): Record<string, unknown> {
    return Object.fromEntries(
        Object.entries(properties).map(([definitionId, value]) => {
            if (value === null) {
                throw new Error(
                    `[HogFunction] - postHogSetAccountProperties received null for property '${definitionId}'. ` +
                        'Use Clear property in the workflow editor, or make the template return a value.'
                )
            }

            return [definitionId, isClearPropertyMarker(value) ? null : value]
        })
    )
}

/**
 * Calls the JWT-only internal account routes (products/customer_analytics/backend/
 * presentation/views/internal.py). The token pins the invocation's own team plus this one
 * account's external_id; Django refuses it anywhere else (#82564).
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
    // Reaches the operator verbatim in the workflow logs. Keep it free of square brackets,
    // which the log viewer parses as entity chips and would swallow.
    if (!context.customerAnalyticsAccountsJwt.enabled) {
        throw new Error(
            `This PostHog deployment has no CUSTOMER_ANALYTICS_ACCOUNTS_JWT_SECRET configured, so ` +
                `${ACCOUNT_ACTIONS} can't authenticate. Set the same value for the web service and the CDP worker.`
        )
    }
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

        await callInternalAccountApi(context, result, externalId, { method: 'GET' })
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

        // external_id spreads last so no updates value can differ from the token's claim —
        // Django rejects a body whose external_id does not match the claim.
        await callInternalAccountApi(context, result, externalId, {
            method: 'PATCH',
            body: JSON.stringify({ ...updates, external_id: externalId }),
            extraHeaders: hogFlowHeaders(context),
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

        const normalizedProperties = normalizeAccountProperties(properties)

        await callInternalAccountApi(context, result, externalId, {
            method: 'PATCH',
            subpath: '/custom_property_values',
            body: JSON.stringify({ external_id: externalId, properties: normalizedProperties }),
            extraHeaders: hogFlowHeaders(context),
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

        await callInternalAccountApi(context, result, externalId, {
            method: 'POST',
            body: JSON.stringify({ external_id: externalId }),
            extraHeaders: hogFlowHeaders(context),
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

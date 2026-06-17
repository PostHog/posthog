import { actions, afterMount, isBreakpoint, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { insightsApi } from 'scenes/insights/utils/api'

import { DataVisualizationNode, HogQLVariable, NodeKind } from '~/queries/schema/schema-general'
import { InsightShortId, QueryBasedInsightModel } from '~/types'

import type { accountBillingLogicType } from './accountBillingLogicType'

export type AccountBillingKind = 'usage' | 'spend'

// Short IDs of the saved billing insights per tab. Absent in environments without them — the tab then shows a not-found state.
export const BILLING_INSIGHT_SHORT_IDS: Record<AccountBillingKind, InsightShortId[]> = {
    usage: ['fiJDsKLp' as InsightShortId],
    spend: ['o4I9sdFE' as InsightShortId, 'Tjo4bsux' as InsightShortId],
}

// code_names of the SQL variables defined on the saved billing insights.
const ORG_VARIABLE = 'billing_org_id'
const START_VARIABLE = 'billing_start_date'
const END_VARIABLE = 'billing_end_date'

export interface BillingDateRange {
    date_from: string | null
    date_to: string | null
}

// Usage insights are daily, spend insights are monthly — so they want different default windows.
const DEFAULT_DATE_RANGE: Record<AccountBillingKind, BillingDateRange> = {
    usage: { date_from: '-30d', date_to: null },
    spend: { date_from: '-1y', date_to: null },
}

export interface AccountBillingLogicProps {
    accountId: string
    externalId: string
    kind: AccountBillingKind
}

// Inject the account's org and the chosen date range into the saved insight's SQL variables, keyed by their
// variableId as read from the fetched insight (so this works regardless of the variable UUIDs in each env).
function buildVariableOverrides(
    insight: QueryBasedInsightModel,
    resolvedDateRange: BillingDateRange,
    externalId: string
): Record<string, HogQLVariable> | undefined {
    const query = insight.query
    if (!query || query.kind !== NodeKind.DataVisualizationNode) {
        return undefined
    }
    const variables = (query as DataVisualizationNode).source.variables
    if (!variables) {
        return undefined
    }
    const valueByCodeName: Record<string, string | null> = {
        [ORG_VARIABLE]: externalId,
        [START_VARIABLE]: resolvedDateRange.date_from,
        [END_VARIABLE]: resolvedDateRange.date_to,
    }
    const overrides: Record<string, HogQLVariable> = {}
    for (const variable of Object.values(variables)) {
        if (variable.code_name in valueByCodeName) {
            overrides[variable.variableId] = {
                ...variable,
                value: valueByCodeName[variable.code_name],
            }
        }
    }
    return overrides
}

export const accountBillingLogic = kea<accountBillingLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountBillingLogic', key]),
    props({} as AccountBillingLogicProps),
    key((props) => `${props.accountId}:${props.kind}`),
    actions({
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
    }),
    reducers(({ props }) => ({
        dateRange: [
            DEFAULT_DATE_RANGE[props.kind] as BillingDateRange,
            {
                setDateRange: (_, { dateFrom, dateTo }) => ({ date_from: dateFrom, date_to: dateTo }),
            },
        ],
    })),
    loaders(({ props }) => ({
        savedInsights: [
            null as QueryBasedInsightModel[] | null,
            {
                loadSavedInsights: async (_ = null, breakpoint) => {
                    const insights = await Promise.all(
                        BILLING_INSIGHT_SHORT_IDS[props.kind].map(async (shortId) => {
                            try {
                                return await insightsApi.getByShortId(shortId)
                            } catch (error) {
                                if (isBreakpoint(error as Error)) {
                                    throw error
                                }
                                posthog.captureException(error as Error, {
                                    scope: 'accountBillingLogic.loadSavedInsights',
                                    shortId,
                                })
                                return null
                            }
                        })
                    )
                    breakpoint()
                    return insights.filter((insight): insight is QueryBasedInsightModel => insight !== null)
                },
            },
        ],
    })),
    selectors({
        // The saved insights filter on a calendar date column, so the range must be resolved to absolute dates.
        resolvedDateRange: [
            (s) => [s.dateRange],
            (dateRange): BillingDateRange => {
                const from = dateStringToDayJs(dateRange.date_from)
                const to = dateRange.date_to ? dateStringToDayJs(dateRange.date_to) : dayjs()
                return {
                    date_from: from ? from.format('YYYY-MM-DD') : null,
                    date_to: to ? to.format('YYYY-MM-DD') : null,
                }
            },
        ],
        variableOverridesByShortId: [
            (s) => [s.savedInsights, s.resolvedDateRange, (_, p) => p.externalId],
            (savedInsights, resolvedDateRange, externalId): Record<string, Record<string, HogQLVariable>> => {
                const overridesByShortId: Record<string, Record<string, HogQLVariable>> = {}
                for (const insight of savedInsights ?? []) {
                    const overrides = buildVariableOverrides(insight, resolvedDateRange, externalId)
                    if (overrides) {
                        overridesByShortId[insight.short_id] = overrides
                    }
                }
                return overridesByShortId
            },
        ],
        // The embedded <Query> only refetches when its query changes, not when variablesOverride changes — so a date
        // change must remount it. Keying on the resolved range gives each insight a key that changes with the range.
        queryKeyFor: [
            (s) => [s.resolvedDateRange, (_, p) => p.accountId, (_, p) => p.kind],
            (resolvedDateRange, accountId, kind) =>
                (shortId: string): string =>
                    `account-billing-${accountId}-${kind}-${shortId}-${resolvedDateRange.date_from}-${resolvedDateRange.date_to}`,
        ],
    }),
    afterMount(({ actions, props }) => {
        if (props.externalId) {
            actions.loadSavedInsights()
        }
    }),
])

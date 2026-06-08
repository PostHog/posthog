import { actions, afterMount, isBreakpoint, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils'
import { insightsApi } from 'scenes/insights/utils/api'

import { DataVisualizationNode, HogQLVariable, NodeKind } from '~/queries/schema/schema-general'
import { InsightShortId, QueryBasedInsightModel } from '~/types'

import type { accountBillingLogicType } from './accountBillingLogicType'

export type AccountBillingKind = 'usage' | 'spend'

// Short IDs of the saved billing insights. Absent in environments without them — the tab then shows a not-found state.
export const BILLING_INSIGHT_SHORT_IDS: Record<AccountBillingKind, InsightShortId> = {
    usage: 'fiJDsKLp' as InsightShortId,
    spend: '9cZ54LsW' as InsightShortId,
}

// code_names of the SQL variables defined on the saved billing insights.
const ORG_VARIABLE = 'billing_org_id'
const START_VARIABLE = 'billing_start_date'
const END_VARIABLE = 'billing_end_date'

export interface BillingDateRange {
    date_from: string | null
    date_to: string | null
}

export interface AccountBillingLogicProps {
    accountId: string
    externalId: string
    kind: AccountBillingKind
}

export const accountBillingLogic = kea<accountBillingLogicType>([
    path((key) => ['scenes', 'customerAnalytics', 'accounts', 'accountBillingLogic', key]),
    props({} as AccountBillingLogicProps),
    key((props) => `${props.accountId}:${props.kind}`),
    actions({
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
    }),
    reducers({
        dateRange: [
            { date_from: '-30d', date_to: null } as BillingDateRange,
            {
                setDateRange: (_, { dateFrom, dateTo }) => ({ date_from: dateFrom, date_to: dateTo }),
            },
        ],
    }),
    loaders(({ props }) => ({
        savedInsight: [
            null as QueryBasedInsightModel | null,
            {
                loadSavedInsight: async (_ = null, breakpoint) => {
                    try {
                        const insight = await insightsApi.getByShortId(BILLING_INSIGHT_SHORT_IDS[props.kind])
                        breakpoint()
                        return insight
                    } catch (error) {
                        if (isBreakpoint(error as Error)) {
                            throw error
                        }
                        posthog.captureException(error as Error, { scope: 'accountBillingLogic.loadSavedInsight' })
                        return null
                    }
                },
            },
        ],
    })),
    selectors({
        // The saved insight filters on the calendar `date` column, so the range must be resolved to absolute dates.
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
        // Inject the account's org and the chosen date range into the saved insight's SQL variables, keyed by their
        // variableId as read from the fetched insight (so this works regardless of the variable UUIDs in each env).
        variableOverrides: [
            (s) => [s.savedInsight, s.resolvedDateRange, (_, p) => p.externalId],
            (savedInsight, resolvedDateRange, externalId): Record<string, HogQLVariable> | undefined => {
                const query = savedInsight?.query
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
            },
        ],
    }),
    afterMount(({ actions, props }) => {
        if (props.externalId) {
            actions.loadSavedInsight()
        }
    }),
])

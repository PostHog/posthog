import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { projectLogic } from 'scenes/projectLogic'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { webAnalyticsAiSummary } from 'products/web_analytics/frontend/generated/api'
import type {
    AISummaryFilterSpecApi,
    AISummaryResponseApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import type { webAnalyticsAISummaryLogicType } from './webAnalyticsAISummaryLogicType'

export const webAnalyticsAISummaryLogic = kea<webAnalyticsAISummaryLogicType>([
    path(['scenes', 'web-analytics', 'webAnalyticsAISummaryLogic']),
    connect(() => ({
        values: [
            projectLogic,
            ['currentProjectId'],
            webAnalyticsLogic,
            [
                'dateFilter',
                'compareFilter',
                'webAnalyticsFilters',
                'conversionGoal',
                'shouldFilterTestAccounts',
                'isPathCleaningEnabled',
            ],
        ],
    })),
    actions({
        loadCachedSummary: true,
        setSummary: (summary: AISummaryResponseApi | null) => ({ summary }),
        generateSummary: true,
        generateSummarySuccess: (summary: AISummaryResponseApi) => ({ summary }),
        generateSummaryFailure: (error: string) => ({ error }),
        setExpanded: (expanded: boolean) => ({ expanded }),
    }),
    reducers({
        summary: [
            null as AISummaryResponseApi | null,
            {
                setSummary: (_, { summary }) => summary,
                generateSummarySuccess: (_, { summary }) => summary,
            },
        ],
        summaryLoading: [
            false,
            {
                generateSummary: () => true,
                generateSummarySuccess: () => false,
                generateSummaryFailure: () => false,
            },
        ],
        errorMessage: [
            null as string | null,
            {
                generateSummary: () => null,
                generateSummaryFailure: (_, { error }) => error,
            },
        ],
        isExpanded: [true, { setExpanded: (_, { expanded }) => expanded }],
    }),
    selectors({
        filterSpec: [
            (s) => [
                s.dateFilter,
                s.compareFilter,
                s.webAnalyticsFilters,
                s.conversionGoal,
                s.shouldFilterTestAccounts,
                s.isPathCleaningEnabled,
            ],
            (
                dateFilter,
                compareFilter,
                webAnalyticsFilters,
                conversionGoal,
                shouldFilterTestAccounts,
                isPathCleaningEnabled
            ): AISummaryFilterSpecApi => {
                let conversion_goal: AISummaryFilterSpecApi['conversion_goal'] = null
                if (conversionGoal) {
                    if ('actionId' in conversionGoal) {
                        conversion_goal = { actionId: conversionGoal.actionId }
                    } else if ('customEventName' in conversionGoal) {
                        conversion_goal = { customEventName: conversionGoal.customEventName }
                    }
                }
                return {
                    date_from: dateFilter.dateFrom ?? '-7d',
                    date_to: dateFilter.dateTo ?? null,
                    compare: !!compareFilter?.compare,
                    properties: webAnalyticsFilters as AISummaryFilterSpecApi['properties'],
                    conversion_goal,
                    filter_test_accounts: shouldFilterTestAccounts,
                    do_path_cleaning: isPathCleaningEnabled,
                }
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        loadCachedSummary: async (_, breakpoint) => {
            await breakpoint(300)
            if (!values.currentProjectId) {
                return
            }
            let result: AISummaryResponseApi | void
            try {
                result = await webAnalyticsAiSummary(String(values.currentProjectId), values.filterSpec, {
                    check: true,
                })
            } catch {
                return
            }
            breakpoint()
            actions.setSummary(result?.summary_text ? result : null)
        },
        generateSummary: async () => {
            if (!values.currentProjectId) {
                actions.generateSummaryFailure('No project selected')
                return
            }
            try {
                const result = await webAnalyticsAiSummary(String(values.currentProjectId), values.filterSpec)
                if (result?.summary_text) {
                    actions.generateSummarySuccess(result)
                } else {
                    actions.generateSummaryFailure('Failed to generate summary')
                }
            } catch (error) {
                const { detail, message } = (error ?? {}) as { detail?: string; message?: string }
                actions.generateSummaryFailure(detail || message || 'Failed to generate summary')
            }
        },
    })),
    subscriptions(({ actions }) => ({
        filterSpec: () => {
            actions.loadCachedSummary()
        },
    })),
])

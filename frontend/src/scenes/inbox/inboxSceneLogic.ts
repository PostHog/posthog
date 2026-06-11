import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { computeInboxTabCounts, reportsForTab } from './inboxMembership'
import type { inboxSceneLogicType } from './inboxSceneLogicType'
import { inboxBulkActionsLogic } from './logics/inboxBulkActionsLogic'
import {
    buildSignalReportListOrdering,
    INBOX_PIPELINE_STATUS_FILTERS,
    inboxFiltersLogic,
} from './logics/inboxFiltersLogic'
import { signalSourcesLogic } from './signalSourcesLogic'
import { InboxTabCounts, InboxTabKey, INBOX_TAB_KEYS, SignalReport } from './types'

const REPORTS_PAGE_SIZE = 200

const SESSION_ANALYSIS_POLL_INTERVAL_MS = 5000

function isInboxTabKey(value: string | undefined): value is InboxTabKey {
    return value !== undefined && (INBOX_TAB_KEYS as string[]).includes(value)
}

export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

    connect(() => ({
        values: [
            signalSourcesLogic,
            ['hasNoSources', 'isSessionAnalysisRunning'],
            inboxFiltersLogic,
            ['scope', 'searchQuery', 'sortField', 'sortDirection', 'sourceProductFilter', 'priorityFilter'],
        ],
        actions: [
            signalSourcesLogic,
            ['loadSourceConfigs'],
            inboxFiltersLogic,
            ['setSearchQuery', 'setSort', 'toggleSourceProduct', 'togglePriority', 'setScope', 'clearFilters'],
            inboxBulkActionsLogic,
            ['clearSelection'],
        ],
    })),

    actions({
        setSelectedReportId: (id: string | null) => ({ id }),
        setActiveTab: (tab: InboxTabKey) => ({ tab }),
        deleteReport: (reportId: string) => ({ reportId }),
        reingestReport: (reportId: string) => ({ reportId }),
        runSessionAnalysis: true,
        runSessionAnalysisSuccess: true,
        runSessionAnalysisFailure: (error: string) => ({ error }),
    }),

    loaders(({ values }) => ({
        reportsResponse: [
            null as CountedPaginatedResponse<SignalReport> | null,
            {
                loadReports: async () => {
                    return await api.signalReports.list({ ...values.reportsListParams, offset: 0 })
                },
                loadMoreReports: async () => {
                    const currentResults = values.reportsResponse?.results ?? []
                    const response = await api.signalReports.list({
                        ...values.reportsListParams,
                        offset: currentResults.length,
                    })
                    return {
                        ...response,
                        results: [...currentResults, ...response.results],
                    }
                },
            },
        ],
    })),

    reducers({
        reportsResponse: {
            deleteReport: (state: CountedPaginatedResponse<SignalReport> | null, { reportId }: { reportId: string }) =>
                state
                    ? { ...state, results: state.results.filter((r) => r.id !== reportId), count: state.count - 1 }
                    : state,
        },
        selectedReportId: [
            null as string | null,
            {
                setSelectedReportId: (_, { id }) => id,
            },
        ],
        activeTab: [
            'pulls' as InboxTabKey,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        isRunningSessionAnalysis: [
            false,
            {
                runSessionAnalysis: () => true,
                runSessionAnalysisSuccess: () => false,
                runSessionAnalysisFailure: () => false,
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'inbox',
                    name: sceneConfigurations[Scene.Inbox].name,
                    iconType: 'inbox',
                },
            ],
        ],
        // List-API params derived from the persisted filters. Status is the fixed pipeline
        // set; source_product / priority / ordering mirror desktop's `useInboxAllReports`.
        reportsListParams: [
            (s) => [s.searchQuery, s.sortField, s.sortDirection, s.sourceProductFilter, s.priorityFilter],
            (searchQuery, sortField, sortDirection, sourceProductFilter, priorityFilter) => ({
                limit: REPORTS_PAGE_SIZE,
                status: INBOX_PIPELINE_STATUS_FILTERS.join(','),
                search: searchQuery.trim() || undefined,
                ordering: buildSignalReportListOrdering(sortField, sortDirection),
                source_product: sourceProductFilter.length > 0 ? sourceProductFilter.join(',') : undefined,
                priority: priorityFilter.length > 0 ? priorityFilter.join(',') : undefined,
            }),
        ],
        reports: [
            (s) => [s.reportsResponse],
            (reportsResponse: CountedPaginatedResponse<SignalReport> | null): SignalReport[] =>
                reportsResponse?.results ?? [],
        ],
        reportsLoading: [
            (s) => [s.reportsResponseLoading],
            (reportsResponseLoading: boolean): boolean => reportsResponseLoading,
        ],
        reportsHasMore: [
            (s) => [s.reportsResponse],
            (reportsResponse: CountedPaginatedResponse<SignalReport> | null): boolean =>
                reportsResponse?.next !== null && reportsResponse?.next !== undefined,
        ],
        tabCounts: [
            (s) => [s.reports, s.scope],
            (reports: SignalReport[], scope): InboxTabCounts => computeInboxTabCounts(reports, scope),
        ],
        visibleReports: [
            (s) => [s.reports, s.activeTab, s.scope],
            (reports: SignalReport[], activeTab: InboxTabKey, scope): SignalReport[] =>
                reportsForTab(reports, activeTab, scope),
        ],
        selectedReport: [
            (s) => [s.reports, s.selectedReportId],
            (reports: SignalReport[], selectedReportId: string | null): SignalReport | null =>
                reports.find((r) => r.id === selectedReportId) ?? null,
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadReports()
        },
        setSort: () => {
            actions.loadReports()
        },
        toggleSourceProduct: () => {
            actions.loadReports()
        },
        togglePriority: () => {
            actions.loadReports()
        },
        clearFilters: () => {
            actions.loadReports()
        },
        deleteReport: async ({ reportId }) => {
            // Reducer handles optimistic removal from list
            if (values.selectedReportId === reportId) {
                actions.setSelectedReportId(null)
            }
            try {
                await api.signalReports.delete(reportId)
                lemonToast.success('Report deleted')
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to delete report')
                actions.loadReports()
            }
        },
        reingestReport: async ({ reportId }) => {
            try {
                await api.signalReports.reingest(reportId)
                lemonToast.success('Reingestion started — signals will be re-grouped')
                if (values.selectedReportId === reportId) {
                    actions.setSelectedReportId(null)
                }
                actions.loadReports()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to start reingestion')
            }
        },
        loadSourceConfigsSuccess: () => {
            clearInterval(cache.sessionAnalysisPollInterval)
            if (values.isSessionAnalysisRunning) {
                cache.sessionAnalysisPollInterval = setInterval(() => {
                    actions.loadSourceConfigs()
                    actions.loadReports()
                }, SESSION_ANALYSIS_POLL_INTERVAL_MS)
            }
        },
        runSessionAnalysis: async () => {
            try {
                await api.signalReports.analyzeSessions()
                lemonToast.success('Session analysis completed')
                actions.runSessionAnalysisSuccess()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to run session analysis')
                actions.runSessionAnalysisFailure(error?.detail || error?.message || 'Failed to run session analysis')
            }
        },
        runSessionAnalysisSuccess: () => {
            actions.loadReports()
        },
        // Bulk dismiss happens in inboxBulkActionsLogic; refresh the list once it lands.
        [inboxBulkActionsLogic.actionTypes.bulkDismissSuccess]: () => {
            actions.loadReports()
        },
    })),

    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadReports()
        },
        beforeUnmount: () => {
            clearInterval(cache.sessionAnalysisPollInterval)
        },
    })),

    actionToUrl(({ values }) => ({
        setActiveTab: () => [
            values.selectedReportId
                ? urls.inboxReport(values.activeTab, values.selectedReportId)
                : urls.inbox(values.activeTab),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
        setSelectedReportId: () => [
            values.selectedReportId
                ? urls.inboxReport(values.activeTab, values.selectedReportId)
                : urls.inbox(values.activeTab),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
    })),

    urlToAction(({ actions, values }) => ({
        [urls.inbox()]: () => {
            if (values.selectedReportId !== null) {
                actions.setSelectedReportId(null)
            }
        },
        [urls.inbox(':tab')]: ({ tab }: { tab?: string }) => {
            if (isInboxTabKey(tab) && values.activeTab !== tab) {
                actions.setActiveTab(tab)
            }
            if (values.selectedReportId !== null) {
                actions.setSelectedReportId(null)
            }
        },
        [urls.inboxReport(':tab', ':reportId')]: ({ tab, reportId }: { tab?: string; reportId?: string }) => {
            if (isInboxTabKey(tab) && values.activeTab !== tab) {
                actions.setActiveTab(tab)
            }
            const id = reportId ?? null
            if (values.selectedReportId !== id) {
                actions.setSelectedReportId(id)
            }
        },
    })),
])

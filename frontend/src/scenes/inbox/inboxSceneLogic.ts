import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { SignalNode } from 'scenes/debug/signals/types'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { inboxSceneLogicType } from './inboxSceneLogicType'
import { signalSourcesLogic } from './signalSourcesLogic'
import {
    EnrichedReviewer,
    SignalReport,
    SignalReportArtefact,
    SignalReportArtefactResponse,
    SignalReportStatus,
} from './types'

const REPORTS_PAGE_SIZE = 200

export type DetailTab = 'overview' | 'signals'

const SESSION_ANALYSIS_POLL_INTERVAL_MS = 5000

// Shared so the deep-link path (deferred until reports settle) and the normal click path emit
// identical `Inbox report opened` properties. Property parity with the PostHog Code clients is
// partial — priority/actionability/source_products are Code-only and absent from the web SignalReport.
function captureReportOpened(reports: SignalReport[], id: string, previousReportId: string | null): void {
    const rank = reports.findIndex((r) => r.id === id)
    const report = reports[rank] ?? null
    posthog.capture('Inbox report opened', {
        report_id: id,
        report_title: report?.title ?? null,
        report_age_hours: report ? dayjs().diff(dayjs(report.created_at), 'hour', true) : null,
        status: report?.status ?? null,
        signal_count: report?.signal_count ?? null,
        rank: rank >= 0 ? rank : null,
        list_size: reports.length,
        previous_report_id: previousReportId,
        surface: 'web',
    })
}

export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

    connect({
        values: [signalSourcesLogic, ['hasNoSources', 'isSessionAnalysisRunning']],
        actions: [signalSourcesLogic, ['loadSourceConfigs']],
    }),

    actions({
        setSelectedReportId: (id: string | null) => ({ id }),
        setSearchQuery: (query: string) => ({ query }),
        setStatusFilters: (statuses: SignalReportStatus[]) => ({ statuses }),
        setActiveDetailTab: (tab: DetailTab) => ({ tab }),
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
                    return await api.signalReports.list({
                        limit: REPORTS_PAGE_SIZE,
                        offset: 0,
                        status: values.statusFilters.length > 0 ? values.statusFilters.join(',') : undefined,
                        search: values.searchQuery.trim() || undefined,
                        ordering: '-is_suggested_reviewer,-signal_count',
                    })
                },
                loadMoreReports: async () => {
                    const currentResults = values.reportsResponse?.results ?? []
                    const response = await api.signalReports.list({
                        limit: REPORTS_PAGE_SIZE,
                        offset: currentResults.length,
                        status: values.statusFilters.length > 0 ? values.statusFilters.join(',') : undefined,
                        search: values.searchQuery.trim() || undefined,
                        ordering: '-is_suggested_reviewer,-signal_count',
                    })
                    return {
                        ...response,
                        results: [...currentResults, ...response.results],
                    }
                },
            },
        ],
        artefacts: [
            {} as Record<string, SignalReportArtefact[]>,
            {
                loadArtefacts: async ({ reportId }: { reportId: string }) => {
                    const response: SignalReportArtefactResponse = await api.signalReports.artefacts(reportId)
                    return { ...values.artefacts, [reportId]: response.results }
                },
            },
        ],
        reportSignals: [
            {} as Record<string, SignalNode[]>,
            {
                loadReportSignals: async ({ reportId }: { reportId: string }) => {
                    const response = await api.signalReports.getReportSignals(reportId)
                    return { ...values.reportSignals, [reportId]: response.signals }
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
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { query }) => query,
            },
        ],
        statusFilters: [
            [SignalReportStatus.READY] as SignalReportStatus[],
            {
                setStatusFilters: (_, { statuses }) => statuses,
            },
        ],
        activeDetailTab: [
            'overview' as DetailTab,
            {
                setActiveDetailTab: (_, { tab }) => tab,
                setSelectedReportId: () => 'overview' as DetailTab,
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
        reports: [
            (s) => [s.reportsResponse],
            (reportsResponse: CountedPaginatedResponse<SignalReport> | null): SignalReport[] =>
                reportsResponse?.results ?? [],
        ],
        reportsLoading: [
            (s) => [s.reportsResponseLoading],
            (reportsResponseLoading: boolean): boolean => reportsResponseLoading,
        ],
        reportsTotal: [
            (s) => [s.reportsResponse],
            (reportsResponse: CountedPaginatedResponse<SignalReport> | null): number => reportsResponse?.count ?? 0,
        ],
        reportsHasMore: [
            (s) => [s.reportsResponse],
            (reportsResponse: CountedPaginatedResponse<SignalReport> | null): boolean =>
                reportsResponse?.next !== null && reportsResponse?.next !== undefined,
        ],
        filteredReports: [(s) => [s.reports], (reports: SignalReport[]): SignalReport[] => reports],
        selectedReport: [
            (s) => [s.reports, s.selectedReportId],
            (reports: SignalReport[], selectedReportId: string | null): SignalReport | null =>
                reports.find((r) => r.id === selectedReportId) ?? null,
        ],
        shouldShowEnablingCtaOnMobile: [
            (s) => [s.hasNoSources, s.filteredReports, s.reportsLoading],
            (hasNoSources: boolean, filteredReports: SignalReport[], reportsLoading: boolean): boolean =>
                hasNoSources && !reportsLoading && filteredReports.length === 0,
        ],
        selectedReportSignals: [
            (s) => [s.reportSignals, s.selectedReportId],
            (reportSignals: Record<string, SignalNode[]>, selectedReportId: string | null): SignalNode[] | null =>
                selectedReportId ? (reportSignals[selectedReportId] ?? null) : null,
        ],
        selectedReportReviewers: [
            (s) => [s.artefacts, s.selectedReportId],
            (
                artefacts: Record<string, SignalReportArtefact[]>,
                selectedReportId: string | null
            ): EnrichedReviewer[] | null => {
                if (!selectedReportId) {
                    return null
                }
                const reportArtefacts = artefacts[selectedReportId]
                if (!reportArtefacts) {
                    return null
                }
                const reviewersArtefact = reportArtefacts.find((a) => a.type === 'suggested_reviewers')
                if (!reviewersArtefact) {
                    return null
                }
                // content is already JSON-decoded by the serializer
                return reviewersArtefact.content as EnrichedReviewer[]
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadReports()
        },
        setStatusFilters: () => {
            actions.loadReports()
        },
        loadReportsSuccess: () => {
            const reports = values.filteredReports
            // Fire `Inbox viewed` once per visit, after reports settle — mirrors the PostHog Code
            // clients so the web surface isn't a blind spot for sales/CS interest alerts.
            if (!cache.inboxViewedTracked) {
                cache.inboxViewedTracked = true
                const isDefaultStatusFilter =
                    values.statusFilters.length === 1 && values.statusFilters[0] === SignalReportStatus.READY
                posthog.capture('Inbox viewed', {
                    report_count: reports.length,
                    total_count: values.reportsTotal,
                    ready_count: reports.filter((r) => r.status === SignalReportStatus.READY).length,
                    has_active_filters: values.searchQuery.trim().length > 0 || !isDefaultStatusFilter,
                    status_filter_count: values.statusFilters.length,
                    is_empty: reports.length === 0,
                    surface: 'web',
                })
            }
            // Flush a deep-link `Inbox report opened` that arrived before reports had loaded, so the
            // event carries real report properties instead of nulls.
            if (cache.pendingReportOpenId) {
                const pendingId = cache.pendingReportOpenId as string
                const pendingPreviousId = (cache.pendingReportOpenPreviousId as string | null) ?? null
                cache.pendingReportOpenId = null
                cache.pendingReportOpenPreviousId = null
                if (values.selectedReportId === pendingId) {
                    captureReportOpened(reports, pendingId, pendingPreviousId)
                }
            }
        },
        setSelectedReportId: ({ id }) => {
            const previousReportId = (cache.previousReportId as string | null) ?? null
            cache.previousReportId = id
            if (id) {
                if (!values.artefacts[id]) {
                    actions.loadArtefacts({ reportId: id })
                }
                if (!values.reportSignals[id]) {
                    actions.loadReportSignals({ reportId: id })
                }
                // Mirror the PostHog Code clients' `Inbox report opened` so sales/CS can alert on
                // report-level interest regardless of surface. On deep-link mount, urlToAction fires
                // this before loadReports resolves; defer the capture so properties aren't all null.
                if (values.reportsResponse === null) {
                    cache.pendingReportOpenId = id
                    cache.pendingReportOpenPreviousId = previousReportId
                } else {
                    captureReportOpened(values.filteredReports, id, previousReportId)
                }
            }
        },
        setActiveDetailTab: ({ tab }) => {
            if (tab === 'signals' && values.selectedReportId && !values.reportSignals[values.selectedReportId]) {
                actions.loadReportSignals({ reportId: values.selectedReportId })
            }
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
                const errorMessage = error?.detail || error?.message || 'Failed to delete report'
                lemonToast.error(errorMessage)
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
                const errorMessage = error?.detail || error?.message || 'Failed to start reingestion'
                lemonToast.error(errorMessage)
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
                const errorMessage = error?.detail || error?.message || 'Failed to run session analysis'
                lemonToast.error(errorMessage)
                actions.runSessionAnalysisFailure(errorMessage)
            }
        },
        runSessionAnalysisSuccess: () => {
            actions.loadReports()
        },
    })),

    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadReports()
        },
        beforeUnmount: () => {
            clearInterval(cache.sessionAnalysisPollInterval)
            cache.inboxViewedTracked = false
            cache.previousReportId = null
            cache.pendingReportOpenId = null
            cache.pendingReportOpenPreviousId = null
        },
    })),

    actionToUrl(({ values }) => ({
        setSelectedReportId: () => [
            values.selectedReportId ? urls.inbox(values.selectedReportId) : urls.inbox(),
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
        [urls.inbox(':reportId')]: ({ reportId }: { reportId?: string }) => {
            const id = reportId ?? null
            if (values.selectedReportId !== id) {
                actions.setSelectedReportId(id)
            }
        },
    })),
])

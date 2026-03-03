import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { SignalNode } from 'scenes/debug/signals/types'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { inboxSceneLogicType } from './inboxSceneLogicType'
import { signalSourcesLogic } from './signalSourcesLogic'
import { SignalReport, SignalReportArtefact, SignalReportArtefactResponse, SignalReportStatus } from './types'

const REPORTS_PAGE_SIZE = 200

export type DetailTab = 'overview' | 'signals'

export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

    connect({
        values: [signalSourcesLogic, ['hasNoSources']],
    }),

    actions({
        setSelectedReportId: (id: string | null) => ({ id }),
        setSearchQuery: (query: string) => ({ query }),
        setStatusFilters: (statuses: SignalReportStatus[]) => ({ statuses }),
        setActiveDetailTab: (tab: DetailTab) => ({ tab }),
        deleteReport: (reportId: string) => ({ reportId }),
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
                    })
                },
                loadMoreReports: async () => {
                    const currentResults = values.reportsResponse?.results ?? []
                    const response = await api.signalReports.list({
                        limit: REPORTS_PAGE_SIZE,
                        offset: currentResults.length,
                        status: values.statusFilters.length > 0 ? values.statusFilters.join(',') : undefined,
                        search: values.searchQuery.trim() || undefined,
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
    }),

    listeners(({ actions, values }) => ({
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadReports()
        },
        setStatusFilters: () => {
            actions.loadReports()
        },
        setSelectedReportId: ({ id }) => {
            if (id) {
                if (!values.artefacts[id]) {
                    actions.loadArtefacts({ reportId: id })
                }
                if (!values.reportSignals[id]) {
                    actions.loadReportSignals({ reportId: id })
                }
            }
        },
        setActiveDetailTab: ({ tab }) => {
            if (tab === 'signals' && values.selectedReportId && !values.reportSignals[values.selectedReportId]) {
                actions.loadReportSignals({ reportId: values.selectedReportId })
            }
        },
        deleteReport: async ({ reportId }) => {
            try {
                await api.signalReports.delete(reportId)
                lemonToast.success('Report deleted')
                if (values.selectedReportId === reportId) {
                    actions.setSelectedReportId(null)
                }
                actions.loadReports()
            } catch (error: any) {
                const errorMessage = error?.detail || error?.message || 'Failed to delete report'
                lemonToast.error(errorMessage)
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

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadReports()
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

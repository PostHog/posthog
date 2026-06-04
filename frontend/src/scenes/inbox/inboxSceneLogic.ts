import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { SignalNode } from 'scenes/debug/signals/types'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    signalsConfigCreate,
    signalsConfigList,
    signalsReportsCursorConnectionCreate,
    signalsReportsCursorConnectionDestroy,
    signalsReportsCursorConnectionRetrieve,
    signalsReportsDispatchCreate,
} from 'products/signals/frontend/generated/api'
import {
    CodingAgentEnumApi,
    CursorConnectionStatusApi,
    SignalTeamConfigApi,
} from 'products/signals/frontend/generated/api.schemas'

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

export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

    connect({
        values: [signalSourcesLogic, ['hasNoSources', 'isSessionAnalysisRunning'], featureFlagLogic, ['featureFlags']],
        actions: [signalSourcesLogic, ['loadSourceConfigs']],
    }),

    actions({
        setSelectedReportId: (id: string | null) => ({ id }),
        setSearchQuery: (query: string) => ({ query }),
        setStatusFilters: (statuses: SignalReportStatus[]) => ({ statuses }),
        setActiveDetailTab: (tab: DetailTab) => ({ tab }),
        deleteReport: (reportId: string) => ({ reportId }),
        reingestReport: (reportId: string) => ({ reportId }),
        requestDispatch: (reportId: string, agent: CodingAgentEnumApi) => ({ reportId, agent }),
        dispatchReport: (reportId: string, agent: CodingAgentEnumApi) => ({ reportId, agent }),
        dispatchReportSuccess: (reportId: string) => ({ reportId }),
        dispatchReportFailure: (reportId: string) => ({ reportId }),
        setShowConnectModal: (show: boolean) => ({ show }),
        setCursorApiKeyDraft: (apiKey: string) => ({ apiKey }),
        setPendingCursorDispatch: (reportId: string | null) => ({ reportId }),
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
        cursorConnection: [
            { connected: false } as CursorConnectionStatusApi,
            {
                loadCursorConnection: async () =>
                    await signalsReportsCursorConnectionRetrieve(String(getCurrentTeamId())),
                connectCursor: async ({ apiKey }: { apiKey: string }) =>
                    await signalsReportsCursorConnectionCreate(String(getCurrentTeamId()), { api_key: apiKey }),
                disconnectCursor: async () => await signalsReportsCursorConnectionDestroy(String(getCurrentTeamId())),
            },
        ],
        teamConfig: [
            null as SignalTeamConfigApi | null,
            {
                loadTeamConfig: async () => await signalsConfigList(String(getCurrentTeamId())),
                saveTeamDefaultAgent: async ({ agent }: { agent: CodingAgentEnumApi }) =>
                    await signalsConfigCreate(String(getCurrentTeamId()), { default_coding_agent: agent }),
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
        dispatchingReportIds: [
            [] as string[],
            {
                dispatchReport: (state: string[], { reportId }: { reportId: string }) =>
                    state.includes(reportId) ? state : [...state, reportId],
                dispatchReportSuccess: (state: string[], { reportId }: { reportId: string }) =>
                    state.filter((id) => id !== reportId),
                dispatchReportFailure: (state: string[], { reportId }: { reportId: string }) =>
                    state.filter((id) => id !== reportId),
            },
        ],
        // Remembers a report the dev tried to send to Cursor while disconnected, so we can
        // auto-dispatch it once the Connect flow succeeds. Cleared on cancel or once dispatched.
        pendingCursorDispatchReportId: [
            null as string | null,
            {
                setPendingCursorDispatch: (_: string | null, { reportId }: { reportId: string | null }) => reportId,
                setShowConnectModal: (state: string | null, { show }: { show: boolean }) => (show ? state : null),
                dispatchReport: () => null,
            },
        ],
        showConnectModal: [
            false,
            {
                setShowConnectModal: (_: boolean, { show }: { show: boolean }) => show,
                connectCursorSuccess: () => false,
            },
        ],
        cursorApiKeyDraft: [
            '',
            {
                setCursorApiKeyDraft: (_: string, { apiKey }: { apiKey: string }) => apiKey,
                connectCursorSuccess: () => '',
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
        canDispatch: [
            (s) => [s.featureFlags],
            (featureFlags: Record<string, boolean | string>): boolean =>
                !!featureFlags[FEATURE_FLAGS.SIGNALS_REPORT_DISPATCH] ||
                !!featureFlags[FEATURE_FLAGS.SIGNALS_CURSOR_DISPATCH],
        ],
        cursorEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: Record<string, boolean | string>): boolean =>
                !!featureFlags[FEATURE_FLAGS.SIGNALS_CURSOR_DISPATCH],
        ],
        isDispatchingSelectedReport: [
            (s) => [s.dispatchingReportIds, s.selectedReportId],
            (dispatchingReportIds: string[], selectedReportId: string | null): boolean =>
                selectedReportId !== null && dispatchingReportIds.includes(selectedReportId),
        ],
        cursorConnected: [
            (s) => [s.cursorConnection],
            (cursorConnection: CursorConnectionStatusApi): boolean => !!cursorConnection?.connected,
        ],
        defaultCodingAgent: [
            (s) => [s.teamConfig],
            (teamConfig: SignalTeamConfigApi | null): CodingAgentEnumApi =>
                teamConfig?.default_coding_agent ?? CodingAgentEnumApi.PosthogCode,
        ],
        // When Cursor is connected but can't actually run agents, surface the wall at connect time.
        cursorConnectionWarning: [
            (s) => [s.cursorConnection],
            (cursorConnection: CursorConnectionStatusApi): string | null => {
                if (!cursorConnection?.connected) {
                    return null
                }
                if (cursorConnection.plan_ok === false) {
                    return 'Connected, but your Cursor account needs a Pro plan to run cloud agents.'
                }
                if (cursorConnection.has_repo_access === false) {
                    return 'Connected, but Cursor has no repository access — connect GitHub in your Cursor account.'
                }
                return null
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
        requestDispatch: ({ reportId, agent }) => {
            // Choosing Cursor while disconnected opens the Connect flow first; the report is
            // remembered and auto-dispatched once the connection succeeds.
            if (agent === CodingAgentEnumApi.Cursor && !values.cursorConnected) {
                actions.setPendingCursorDispatch(reportId)
                actions.setShowConnectModal(true)
                return
            }
            actions.dispatchReport(reportId, agent)
        },
        dispatchReport: async ({ reportId, agent }) => {
            try {
                const response = await signalsReportsDispatchCreate(String(getCurrentTeamId()), reportId, { agent })
                if (response.agent === CodingAgentEnumApi.Cursor) {
                    const agentUrl = response.agent_url
                    lemonToast.success(
                        'Sent to Cursor — a cloud agent is now working on this report',
                        agentUrl
                            ? {
                                  button: {
                                      label: 'View agent in Cursor',
                                      action: () => window.open(agentUrl, '_blank', 'noopener,noreferrer'),
                                  },
                              }
                            : undefined
                    )
                } else {
                    lemonToast.success(
                        'PostHog Code is on it — the implementation PR will appear on this report when it’s ready'
                    )
                    actions.loadReports()
                }
                actions.dispatchReportSuccess(reportId)
            } catch (error: any) {
                const errorMessage = error?.detail || error?.message || 'Failed to dispatch report'
                lemonToast.error(errorMessage)
                actions.dispatchReportFailure(reportId)
            }
        },
        connectCursorSuccess: () => {
            lemonToast.success('Cursor connected')
            if (values.pendingCursorDispatchReportId) {
                actions.dispatchReport(values.pendingCursorDispatchReportId, CodingAgentEnumApi.Cursor)
            }
        },
        connectCursorFailure: () => {
            lemonToast.error('Failed to connect Cursor — check the API key')
        },
        disconnectCursorSuccess: () => {
            lemonToast.success('Cursor disconnected')
        },
        disconnectCursorFailure: () => {
            lemonToast.error('Failed to disconnect Cursor')
        },
        saveTeamDefaultAgentSuccess: () => {
            lemonToast.success('Default coding agent updated')
        },
        saveTeamDefaultAgentFailure: () => {
            lemonToast.error('Failed to update the default coding agent')
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
            actions.loadCursorConnection()
            actions.loadTeamConfig()
        },
        beforeUnmount: () => {
            clearInterval(cache.sessionAnalysisPollInterval)
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

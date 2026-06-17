import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Breadcrumb } from '~/types'

import { isAgentRunReport, isFinishedRunReport } from './inboxMembership'
import type { inboxSceneLogicType } from './inboxSceneLogicType'
import { INBOX_PIPELINE_STATUS_FILTERS } from './logics/inboxFiltersLogic'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from './logics/reportListLogic'
import { signalSourcesLogic } from './signalSourcesLogic'
import {
    InboxFlatListTabKey,
    INBOX_STAFF_ONLY_TAB_KEYS,
    INBOX_TAB_KEYS,
    INBOX_TAB_LABEL,
    InboxTabKey,
    SignalReport,
} from './types'
import { displayConventionalCommitTitle } from './utils/reportPresentation'

const RUNS_PAGE_SIZE = 200

const SESSION_ANALYSIS_POLL_INTERVAL_MS = 5000

function isInboxTabKey(value: string | undefined): value is InboxTabKey {
    return value !== undefined && (INBOX_TAB_KEYS as string[]).includes(value)
}

function isStaffOnlyTab(tab: string | undefined): boolean {
    return tab !== undefined && (INBOX_STAFF_ONLY_TAB_KEYS as string[]).includes(tab)
}

/**
 * Find a report already loaded in one of the mounted per-tab lists (or the staff Runs list),
 * so opening it can render the detail instantly from the list row instead of waiting on a fresh
 * `GET`. The background fetch still runs to converge on the authoritative record.
 */
function findLoadedReport(id: string, runsReports: SignalReport[]): SignalReport | null {
    const fromRuns = runsReports.find((r) => r.id === id)
    if (fromRuns) {
        return fromRuns
    }
    for (const tabKey of Object.keys(INBOX_FLAT_TAB_LIST_PARAMS) as InboxFlatListTabKey[]) {
        const mounted = reportListLogic.findMounted({ tabKey, listParams: INBOX_FLAT_TAB_LIST_PARAMS[tabKey] })
        const found = mounted?.values.reports.find((r) => r.id === id)
        if (found) {
            return found
        }
    }
    return null
}

/**
 * Inbox scene orchestrator. Owns the active tab, the selected report (loaded by id),
 * the staff-only project-wide Runs list, and session-analysis. The per-tab report
 * lists + their counts live in the keyed `reportListLogic` (one instance per flat tab),
 * so this logic no longer holds a shared report list.
 */
export const inboxSceneLogic = kea<inboxSceneLogicType>([
    path(['scenes', 'inbox', 'inboxSceneLogic']),

    connect(() => ({
        values: [signalSourcesLogic, ['isSessionAnalysisRunning'], userLogic, ['user']],
        actions: [signalSourcesLogic, ['loadSourceConfigs']],
    })),

    actions({
        setSelectedReportId: (id: string | null) => ({ id }),
        // Seed (or clear) the selected report synchronously from an already-loaded list row, so the
        // detail renders without a spinner while the authoritative fetch runs in the background.
        seedSelectedReport: (report: SignalReport | null) => ({ report }),
        setActiveTab: (tab: InboxTabKey) => ({ tab }),
        runSessionAnalysis: true,
        runSessionAnalysisSuccess: true,
        runSessionAnalysisFailure: (error: string) => ({ error }),
    }),

    loaders(() => ({
        // Staff-only Runs tab: project-wide, UNFILTERED (no reviewer scope / source / priority / search) –
        // every report whose run is in progress or has concluded.
        runsResponse: [
            null as CountedPaginatedResponse<SignalReport> | null,
            {
                loadRuns: async () => {
                    return await api.signalReports.list({
                        status: INBOX_PIPELINE_STATUS_FILTERS.join(','),
                        ordering: 'status,-updated_at',
                        limit: RUNS_PAGE_SIZE,
                    })
                },
            },
        ],
        // The selected report's base record, loaded by id so detail works regardless of which
        // tab/list it came from (and on direct deep-link).
        selectedReportResponse: [
            null as SignalReport | null,
            {
                loadSelectedReport: async ({ id }: { id: string }) => {
                    return await api.signalReports.get(id)
                },
            },
        ],
    })),

    reducers({
        selectedReportResponse: {
            // Navigation seeds this directly: the listener resolves the list row (or null) and
            // dispatches `seedSelectedReport` in the same tick, so we never flash through a stale
            // report or a spinner when the row is already loaded. The loader repopulates it on fetch.
            seedSelectedReport: (_, { report }) => report,
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
            (s) => [s.selectedReportId, s.selectedReport, s.activeTab],
            (selectedReportId, selectedReport, activeTab): Breadcrumb[] => {
                // List view: the product root is the current page, so it carries no link.
                if (!selectedReportId) {
                    return [{ key: 'inbox', name: sceneConfigurations[Scene.Inbox].name, iconType: 'inbox' }]
                }
                // Detail view: root → active tab (the canonical "back" link) → this report's title.
                return [
                    {
                        key: 'inbox',
                        name: sceneConfigurations[Scene.Inbox].name,
                        path: urls.inbox(),
                        iconType: 'inbox',
                    },
                    { key: [Scene.Inbox, activeTab], name: INBOX_TAB_LABEL[activeTab], path: urls.inbox(activeTab) },
                    {
                        key: [Scene.Inbox, selectedReportId],
                        name: selectedReport
                            ? displayConventionalCommitTitle(selectedReport.title, 'Untitled report')
                            : null,
                    },
                ]
            },
        ],
        isStaff: [() => [userLogic.selectors.user], (user): boolean => user?.is_staff ?? false],
        runsTabReports: [
            (s) => [s.runsResponse],
            (runsResponse: CountedPaginatedResponse<SignalReport> | null): SignalReport[] =>
                (runsResponse?.results ?? []).filter((r) => isAgentRunReport(r) || isFinishedRunReport(r)),
        ],
        runsCount: [(s) => [s.runsTabReports], (runsTabReports: SignalReport[]): number => runsTabReports.length],
        selectedReport: [
            (s) => [s.selectedReportResponse],
            (selectedReportResponse: SignalReport | null): SignalReport | null => selectedReportResponse,
        ],
        selectedReportLoading: [
            (s) => [s.selectedReportResponseLoading],
            (selectedReportResponseLoading: boolean): boolean => selectedReportResponseLoading,
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        setActiveTab: ({ tab }) => {
            // Refresh the project-wide runs list each time the (staff-only) Runs tab opens.
            if (tab === 'runs' && values.isStaff) {
                actions.loadRuns()
            }
        },
        setSelectedReportId: ({ id }) => {
            if (!id) {
                actions.seedSelectedReport(null)
                return
            }
            // Reuse the list row if we already have it (instant render), then refresh from the server.
            actions.seedSelectedReport(findLoadedReport(id, values.runsTabReports))
            actions.loadSelectedReport({ id })
        },
        loadSourceConfigsSuccess: () => {
            clearInterval(cache.sessionAnalysisPollInterval)
            if (values.isSessionAnalysisRunning) {
                cache.sessionAnalysisPollInterval = setInterval(() => {
                    actions.loadSourceConfigs()
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
    })),

    events(({ actions, values, cache }) => ({
        afterMount: () => {
            // Runs is a staff-only (internal) tab; only fetch its list for staff users.
            if (values.isStaff) {
                actions.loadRuns()
            }
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
            // Staff-only tabs (Runs, Not actionable): bounce non-staff to the default tab.
            if (isStaffOnlyTab(tab) && userLogic.values.user != null && !values.isStaff) {
                actions.setActiveTab('pulls')
                return
            }
            if (isInboxTabKey(tab) && values.activeTab !== tab) {
                actions.setActiveTab(tab)
            }
            if (values.selectedReportId !== null) {
                actions.setSelectedReportId(null)
            }
        },
        [urls.inboxReport(':tab', ':reportId')]: ({ tab, reportId }: { tab?: string; reportId?: string }) => {
            if (isStaffOnlyTab(tab) && userLogic.values.user != null && !values.isStaff) {
                actions.setActiveTab('pulls')
                return
            }
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

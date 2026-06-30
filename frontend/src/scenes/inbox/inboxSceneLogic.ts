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

import {
    captureInboxReportClosed,
    captureInboxReportOpened,
    InboxReportCloseMethod,
    InboxReportOpenMethod,
} from './inboxAnalytics'
import { isAgentRunReport, isFinishedRunReport } from './inboxMembership'
import type { inboxSceneLogicType } from './inboxSceneLogicType'
import { INBOX_PIPELINE_STATUS_FILTERS } from './logics/inboxFiltersLogic'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from './logics/reportListLogic'
import { scratchpadLogic } from './logics/scratchpadLogic'
import { signalSourcesLogic } from './signalSourcesLogic'
import { InboxFlatListTabKey, INBOX_STAFF_ONLY_TAB_KEYS, INBOX_TAB_KEYS, InboxTabKey, SignalReport } from './types'

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
// The Fleet memory callout reads the same singleton `scratchpadLogic` the panel filters, so a
// leftover search (especially a no-match one) would make it count zero and hide itself. Clear the
// search whenever the scratchpad closes — by any path (close button, report/scout open, Back nav).
function clearScratchpadSearch(): void {
    const mounted = scratchpadLogic.findMounted()
    if (mounted?.values.searchText) {
        mounted.actions.setSearchText('')
    }
}

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
 * Position (1-based) and size of the report's list, for `Inbox report opened`. Prefers the active
 * Runs list when it's open, then any mounted flat-tab list that holds the report. Null when the
 * report isn't in a loaded list (e.g. a cold deep-link).
 */
function findReportRank(
    id: string,
    activeTab: InboxTabKey,
    runsReports: SignalReport[]
): { rank: number | null; listSize: number | null } {
    const lists: SignalReport[][] = []
    if (activeTab === 'runs') {
        lists.push(runsReports)
    }
    for (const tabKey of Object.keys(INBOX_FLAT_TAB_LIST_PARAMS) as InboxFlatListTabKey[]) {
        const mounted = reportListLogic.findMounted({ tabKey, listParams: INBOX_FLAT_TAB_LIST_PARAMS[tabKey] })
        if (mounted) {
            lists.push(mounted.values.reports)
        }
    }
    for (const list of lists) {
        const idx = list.findIndex((r) => r.id === id)
        if (idx >= 0) {
            return { rank: idx + 1, listSize: list.length }
        }
    }
    return { rank: null, listSize: null }
}

/**
 * The URL for whichever full-width inbox surface is open, or the list otherwise. The four (report,
 * scout detail, scratchpad, findings) are mutually exclusive, so a fixed priority order resolves them.
 */
function inboxSurfaceUrl(values: {
    selectedReportId: string | null
    activeTab: InboxTabKey
    selectedScoutSkillName: string | null
    selectedScoutFindingId: string | null
    isScratchpadOpen: boolean
    isFindingsOpen: boolean
}): string {
    if (values.selectedReportId) {
        return urls.inboxReport(values.activeTab, values.selectedReportId)
    }
    if (values.selectedScoutSkillName) {
        return urls.inboxScout(values.selectedScoutSkillName, values.selectedScoutFindingId ?? undefined)
    }
    if (values.isScratchpadOpen) {
        return urls.inboxScratchpad()
    }
    if (values.isFindingsOpen) {
        return urls.inboxFindings()
    }
    return urls.inbox(values.activeTab)
}

/** Open-report engagement tracking state, kept on the logic's `cache` (not reactive). */
interface InboxOpenTracking {
    report: SignalReport
    openedAt: number
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
        setSelectedReportId: (id: string | null, openMethod: InboxReportOpenMethod = 'unknown') => ({
            id,
            openMethod,
        }),
        // Seed (or clear) the selected report synchronously from an already-loaded list row, so the
        // detail renders without a spinner while the authoritative fetch runs in the background.
        seedSelectedReport: (report: SignalReport | null) => ({ report }),
        setActiveTab: (tab: InboxTabKey) => ({ tab }),
        // Scout detail surface: selecting a scout opens its full-width detail over the list. An
        // optional finding id deep-links to one emitted finding within that scout (highlighted +
        // scrolled into view if it's still in the recent window).
        setSelectedScoutSkillName: (skillName: string | null, findingId: string | null = null) => ({
            skillName,
            findingId,
        }),
        // Scout fleet-memory (scratchpad) surface: a full-width browse/search view over the list,
        // mutually exclusive with the report and scout-detail views. Reached from the fleet-memory callout.
        setScratchpadOpen: (open: boolean) => ({ open }),
        // Cross-fleet findings surface: full-width browse/search/filter of every finding the troop
        // emitted recently, mutually exclusive with the other full-width views.
        setFindingsOpen: (open: boolean) => ({ open }),
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
        selectedScoutSkillName: [
            null as string | null,
            {
                setSelectedScoutSkillName: (_, { skillName }) => skillName,
            },
        ],
        isScratchpadOpen: [
            false,
            {
                setScratchpadOpen: (_, { open }) => open,
                // Opening a report, a scout, or the findings view closes the memory view.
                setSelectedReportId: (state, { id }) => (id ? false : state),
                setSelectedScoutSkillName: (state, { skillName }) => (skillName ? false : state),
                setFindingsOpen: (state, { open }) => (open ? false : state),
            },
        ],
        isFindingsOpen: [
            false,
            {
                setFindingsOpen: (_, { open }) => open,
                // Opening a report, a scout, or the memory view closes the findings view.
                setSelectedReportId: (state, { id }) => (id ? false : state),
                setSelectedScoutSkillName: (state, { skillName }) => (skillName ? false : state),
                setScratchpadOpen: (state, { open }) => (open ? false : state),
            },
        ],
        // The finding deep-linked within the selected scout, if any. Cleared whenever a scout is
        // (re)selected without a finding — navigating to a scout from the fleet drops any prior finding.
        selectedScoutFindingId: [
            null as string | null,
            {
                setSelectedScoutSkillName: (_, { findingId }) => findingId,
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
        setSelectedReportId: ({ id, openMethod }) => {
            // Close the previously open report (if any) before opening/clearing. `next_report` when
            // switching straight to another report, `deselected` when returning to the list.
            const open: InboxOpenTracking | undefined = cache.openTracking
            if (open) {
                const closeMethod: InboxReportCloseMethod = id ? 'next_report' : 'deselected'
                captureInboxReportClosed({
                    report: open.report,
                    timeSpentMs: Date.now() - open.openedAt,
                    closeMethod,
                })
                cache.previousReportId = open.report.id
                cache.openTracking = undefined
            }
            if (!id) {
                actions.seedSelectedReport(null)
                return
            }
            // Opening a report closes the scratchpad (reducer) — clear its transient search so the
            // callout doesn't stay hidden behind a stale no-match filter on the way back.
            clearScratchpadSearch()
            // The open method is resolved once the authoritative record lands in loadSelectedReportSuccess.
            cache.pendingOpenMethod = openMethod
            // A report and a scout detail are mutually exclusive full-width views.
            if (values.selectedScoutSkillName !== null) {
                actions.setSelectedScoutSkillName(null)
            }
            // Reuse the list row if we already have it (instant render), then refresh from the server.
            actions.seedSelectedReport(findLoadedReport(id, values.runsTabReports))
            actions.loadSelectedReport({ id })
        },
        // Fire `Inbox report opened` once the authoritative record lands (skip background refreshes
        // of the already-open report). Rank/list_size come from whichever loaded list holds it.
        loadSelectedReportSuccess: ({ selectedReportResponse }) => {
            const report = selectedReportResponse
            // Skip already-open refreshes, and stale loads for a report the user already navigated away
            // from before the fetch returned (else we'd log a phantom open + a later bogus dwell close).
            if (!report || values.selectedReportId !== report.id || cache.openTracking?.report.id === report.id) {
                return
            }
            const { rank, listSize } = findReportRank(report.id, values.activeTab, values.runsTabReports)
            captureInboxReportOpened({
                report,
                openMethod: (cache.pendingOpenMethod as InboxReportOpenMethod | undefined) ?? 'unknown',
                previousReportId: cache.previousReportId ?? null,
                rank,
                listSize,
            })
            cache.openTracking = { report, openedAt: Date.now() }
            cache.pendingOpenMethod = undefined
        },
        setSelectedScoutSkillName: ({ skillName }) => {
            if (skillName !== null) {
                // Opening a scout detail closes the scratchpad (reducer) — clear its transient search.
                clearScratchpadSearch()
                if (values.selectedReportId !== null) {
                    actions.setSelectedReportId(null)
                }
            }
        },
        setScratchpadOpen: ({ open }) => {
            if (open) {
                // Close the open report/scout through their own actions so report dwell-time
                // bookkeeping runs (clearing the id in a reducer would skip the close tracking).
                if (values.selectedReportId !== null) {
                    actions.setSelectedReportId(null)
                }
                if (values.selectedScoutSkillName !== null) {
                    actions.setSelectedScoutSkillName(null)
                }
            } else {
                clearScratchpadSearch()
            }
        },
        setFindingsOpen: ({ open }) => {
            if (open) {
                // Same dwell-tracking-preserving close as the scratchpad path; clear its transient
                // search so the memory callout isn't left hidden behind a stale filter on the way back.
                clearScratchpadSearch()
                if (values.selectedReportId !== null) {
                    actions.setSelectedReportId(null)
                }
                if (values.selectedScoutSkillName !== null) {
                    actions.setSelectedScoutSkillName(null)
                }
            }
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
            // Flush dwell time for a report still open when the scene unmounts (navigated away).
            const open: InboxOpenTracking | undefined = cache.openTracking
            if (open) {
                captureInboxReportClosed({
                    report: open.report,
                    timeSpentMs: Date.now() - open.openedAt,
                    closeMethod: 'unmount',
                })
                cache.openTracking = undefined
            }
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
        // Each toggle resolves to whichever full-width view is left open (or the list), so clearing one
        // because another opened honors that surface's URL rather than bouncing to the list.
        setSelectedReportId: () => [
            inboxSurfaceUrl(values),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
        setSelectedScoutSkillName: () => [
            inboxSurfaceUrl(values),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
        setScratchpadOpen: () => [
            inboxSurfaceUrl(values),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
        setFindingsOpen: () => [
            inboxSurfaceUrl(values),
            router.values.searchParams,
            router.values.hashParams,
            { replace: false },
        ],
    })),

    urlToAction(({ actions, values, cache }) => ({
        [urls.inboxScratchpad()]: () => {
            if (!values.isScratchpadOpen) {
                actions.setScratchpadOpen(true)
            }
        },
        [urls.inboxFindings()]: () => {
            if (!values.isFindingsOpen) {
                actions.setFindingsOpen(true)
            }
        },
        [urls.inbox()]: () => {
            cache.inboxListVisited = true
            if (values.selectedReportId !== null) {
                actions.setSelectedReportId(null)
            }
            if (values.selectedScoutSkillName !== null) {
                actions.setSelectedScoutSkillName(null)
            }
            if (values.isScratchpadOpen) {
                actions.setScratchpadOpen(false)
            }
            if (values.isFindingsOpen) {
                actions.setFindingsOpen(false)
            }
        },
        [urls.inbox(':tab')]: ({ tab }: { tab?: string }) => {
            // A bare report deep-link `/inbox/<reportId>`  redirected to report form. Mark the list as
            // visited only when we're actually staying on a list view — otherwise the redirected report
            // would be misclassified as an in-app click instead of a deep-link.
            if (tab && !isInboxTabKey(tab) && tab !== 'scouts') {
                router.actions.replace(
                    urls.inboxReport('reports', tab),
                    router.values.searchParams,
                    router.values.hashParams
                )
                return
            }
            cache.inboxListVisited = true
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
            if (values.selectedScoutSkillName !== null) {
                actions.setSelectedScoutSkillName(null)
            }
            if (values.isScratchpadOpen) {
                actions.setScratchpadOpen(false)
            }
            if (values.isFindingsOpen) {
                actions.setFindingsOpen(false)
            }
        },
        [urls.inboxScout(':skillName')]: ({ skillName }: { skillName?: string }) => {
            // `/inbox/scouts/scratchpad` and `/inbox/scouts/findings` also match this pattern; their own
            // handlers own those paths (no real scout skill_name collides — they're `signals-scout-*`).
            if (skillName === 'scratchpad' || skillName === 'findings') {
                return
            }
            const name = skillName ?? null
            // Also reset the finding when landing on the bare scout URL after a finding deep-link.
            if (values.selectedScoutSkillName !== name || values.selectedScoutFindingId !== null) {
                actions.setSelectedScoutSkillName(name)
            }
        },
        [urls.inboxScout(':skillName', ':findingId')]: ({
            skillName,
            findingId,
        }: {
            skillName?: string
            findingId?: string
        }) => {
            const name = skillName ?? null
            const finding = findingId ?? null
            if (values.selectedScoutSkillName !== name || values.selectedScoutFindingId !== finding) {
                actions.setSelectedScoutSkillName(name, finding)
            }
        },
        [urls.inboxReport(':tab', ':reportId')]: ({ tab, reportId }: { tab?: string; reportId?: string }) => {
            // This pattern also matches `/inbox/scouts/<skillName>`; the scout handler owns that path.
            if (tab === 'scouts') {
                return
            }
            if (isStaffOnlyTab(tab) && userLogic.values.user != null && !values.isStaff) {
                actions.setActiveTab('pulls')
                return
            }
            if (isInboxTabKey(tab) && values.activeTab !== tab) {
                actions.setActiveTab(tab)
            }
            const id = reportId ?? null
            if (values.selectedReportId !== id) {
                // First route to a report before any list URL was seen → cold deep-link; otherwise an in-app click.
                actions.setSelectedReportId(id, id ? (cache.inboxListVisited ? 'click' : 'deeplink') : 'unknown')
            }
        },
    })),
])

import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Breadcrumb } from '~/types'

import { OriginProduct, Task, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import {
    captureInboxReportClosed,
    captureInboxReportOpened,
    InboxReportCloseMethod,
    InboxReportOpenMethod,
} from './inboxAnalytics'
import type { inboxSceneLogicType } from './inboxSceneLogicType'
import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from './logics/reportListLogic'
import { scratchpadLogic } from './logics/scratchpadLogic'
import { signalSourcesLogic } from './signalSourcesLogic'
import {
    InboxFlatListTabKey,
    INBOX_STAFF_ONLY_TAB_KEYS,
    INBOX_TAB_KEYS,
    InboxTabKey,
    SignalReport,
    SignalRun,
    SignalScoutRunStatus,
    SignalScoutRunSummary,
} from './types'

// Newest-first scout runs to pull for the Runs tab. The scout-runs endpoint caps at 100 server-side.
const SCOUT_RUNS_LIMIT = 100
// Signal-pipeline tasks to pull. Bounded symmetrically with the scout side (the tasks endpoint caps
// at 100); passed explicitly so the cap is visible rather than relying on the server default.
const SIGNAL_TASKS_LIMIT = 100
// How often the Runs tab refetches while it's open, so live runs update in place.
const RUNS_POLL_INTERVAL_MS = 5000

const SESSION_ANALYSIS_POLL_INTERVAL_MS = 5000

// `TaskRunStatus` and `SignalScoutRunStatus` enumerate the same run states. This `Record` keyed on the
// enum makes the relationship exhaustive: a new `TaskRunStatus` value breaks the build here instead of
// silently rendering as 'queued', so the two type vocabularies can't drift unnoticed.
const TASK_RUN_STATUS_TO_SCOUT_STATUS: Record<TaskRunStatus, SignalScoutRunStatus> = {
    [TaskRunStatus.NOT_STARTED]: 'not_started',
    [TaskRunStatus.QUEUED]: 'queued',
    [TaskRunStatus.IN_PROGRESS]: 'in_progress',
    [TaskRunStatus.COMPLETED]: 'completed',
    [TaskRunStatus.FAILED]: 'failed',
    [TaskRunStatus.CANCELLED]: 'cancelled',
}

/**
 * Merge the Runs tab's two sources — scout runs and signal-pipeline tasks — into one newest-first
 * `SignalRun[]`. Pure (no I/O) so the merge/sort/normalize contract is unit-testable directly.
 * Scout runs without a backing `task_id` are dropped (they can't deep-link to a task); signal rows
 * fall back to the task's own timestamp / a null status when no run exists yet.
 */
export function mergeSignalRuns(scoutRuns: SignalScoutRunSummary[], signalTasks: Task[]): SignalRun[] {
    const scoutRows = scoutRuns
        .filter((run): run is SignalScoutRunSummary & { task_id: string } => !!run.task_id)
        .map(
            (run): SignalRun => ({
                task_id: run.task_id,
                kind: 'scout',
                title: run.skill_name,
                status: run.status,
                report_id: null,
                created_at: run.created_at,
            })
        )
    const signalRows = signalTasks.map((task): SignalRun => {
        const latestStatus = task.latest_run?.status
        return {
            task_id: task.id,
            kind: 'signal',
            title: task.title,
            status: latestStatus ? TASK_RUN_STATUS_TO_SCOUT_STATUS[latestStatus] : null,
            report_id: task.signal_report,
            created_at: task.latest_run?.created_at ?? task.created_at,
        }
    })
    return [...scoutRows, ...signalRows].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
}

function isInboxTabKey(value: string | undefined): value is InboxTabKey {
    return value !== undefined && (INBOX_TAB_KEYS as string[]).includes(value)
}

function isStaffOnlyTab(tab: string | undefined): boolean {
    return tab !== undefined && (INBOX_STAFF_ONLY_TAB_KEYS as string[]).includes(tab)
}

/**
 * Find a report already loaded in one of the mounted per-tab lists, so opening it can render the
 * detail instantly from the list row instead of waiting on a fresh
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

function findLoadedReport(id: string): SignalReport | null {
    for (const tabKey of Object.keys(INBOX_FLAT_TAB_LIST_PARAMS) as InboxFlatListTabKey[]) {
        const mounted = reportListLogic.findMounted({ tabKey, listParams: INBOX_FLAT_TAB_LIST_PARAMS[tabKey] })
        const found = mounted?.values.reports.find((r: SignalReport) => r.id === id)
        if (found) {
            return found
        }
    }
    return null
}

/**
 * Position (1-based) and size of the report's list, for `Inbox report opened`. Searches the mounted
 * flat-tab lists for the report. Null when the report isn't in a loaded list (e.g. a cold deep-link).
 */
function findReportRank(id: string): { rank: number | null; listSize: number | null } {
    for (const tabKey of Object.keys(INBOX_FLAT_TAB_LIST_PARAMS) as InboxFlatListTabKey[]) {
        const mounted = reportListLogic.findMounted({ tabKey, listParams: INBOX_FLAT_TAB_LIST_PARAMS[tabKey] })
        const reports = mounted?.values.reports
        if (!reports) {
            continue
        }
        const idx = reports.findIndex((r: SignalReport) => r.id === id)
        if (idx >= 0) {
            return { rank: idx + 1, listSize: reports.length }
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
 * the project-wide Runs list, and session-analysis. The per-tab report
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
        // Runs tab: a newest-first list of scout + signals-pipeline runs, composed from two existing
        // endpoints, scout runs (clean `skill_name`) and signal-pipeline tasks (whose title is the
        // originating report's title). Merged client-side; there is no unified backend "runs" resource
        // by design. Both endpoints are team-scoped and readable by any member, so the tab is public.
        signalRunsResponse: [
            null as SignalRun[] | null,
            {
                loadRuns: async (_payload: void, breakpoint) => {
                    const [scoutResult, signalResult] = await Promise.allSettled([
                        api.signalScout.runs.list({ limit: SCOUT_RUNS_LIMIT }),
                        // `internal: 'all'` so the pipeline's research runs (created internal) are included,
                        // not just the non-internal implementation/PR runs.
                        api.tasks.list({
                            origin_product: OriginProduct.SIGNAL_REPORT,
                            internal: 'all',
                            limit: SIGNAL_TASKS_LIMIT,
                        }),
                    ])
                    breakpoint()
                    // Degrade gracefully: surface whichever source resolved, matching the inbox's other
                    // fan-out loaders (scoutDetailLogic) so one source's outage doesn't blank the tab.
                    // Only fail the load if both sources rejected.
                    if (scoutResult.status === 'rejected' && signalResult.status === 'rejected') {
                        throw scoutResult.reason
                    }
                    const scoutRuns = scoutResult.status === 'fulfilled' ? scoutResult.value : []
                    const signalTasks = signalResult.status === 'fulfilled' ? signalResult.value.results : []
                    return mergeSignalRuns(scoutRuns, signalTasks)
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
        signalRuns: [
            (s) => [s.signalRunsResponse],
            (signalRunsResponse: SignalRun[] | null): SignalRun[] => signalRunsResponse ?? [],
        ],
        // True only while the first load is in flight (response still null), so the Runs tab shows a
        // skeleton instead of the empty state before any data lands. A refetch on tab re-open keeps the
        // already-loaded list visible rather than flashing the skeleton.
        signalRunsLoading: [
            (s) => [s.signalRunsResponse, s.signalRunsResponseLoading],
            (signalRunsResponse: SignalRun[] | null, signalRunsResponseLoading: boolean): boolean =>
                signalRunsResponse === null && signalRunsResponseLoading,
        ],
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
            // While the Runs tab is open, refetch on a slow poll so live runs update in place. The
            // keyed disposable replaces any prior poll and is torn down on tab switch / unmount, and
            // kea-disposables pauses it while the browser tab is hidden. The refetch is silent (the
            // skeleton only shows before the first load), so it swaps the list without flicker.
            if (tab === 'runs') {
                actions.loadRuns()
                cache.disposables.add(() => {
                    const interval = setInterval(() => actions.loadRuns(), RUNS_POLL_INTERVAL_MS)
                    return () => clearInterval(interval)
                }, 'runsPoll')
            } else {
                cache.disposables.dispose('runsPoll')
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
            actions.seedSelectedReport(findLoadedReport(id))
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
            const { rank, listSize } = findReportRank(report.id)
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

    events(({ cache }) => ({
        // The Runs list loads lazily when its tab opens (via the `setActiveTab` listener). There is no
        // mount pre-fetch, so an inbox visit that never opens Runs doesn't pay for its two requests.
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
            // Staff-only tabs (Not actionable): bounce non-staff to the default tab.
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

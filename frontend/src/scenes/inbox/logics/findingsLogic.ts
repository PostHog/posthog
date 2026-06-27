import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import {
    LinkedSignalReport,
    SignalReportPriority,
    SignalScoutEmission,
    SignalScoutEmissionReportLink,
    SignalScoutRunSummary,
} from '../types'
import { mostRecentEmittedRuns, prettifyScoutSkillName } from '../utils/scoutRunsWindow'
import type { findingsLogicType } from './findingsLogicType'
import { ScoutEmissionRow } from './scoutDetailLogic'
import { scoutFleetLogic } from './scoutFleetLogic'

// Report linkage is eventually consistent, so keep retrying the reverse lookup on the runs-window
// poll, but only while a recently-emitted finding is still unlinked (past this it never will be).
const REPORT_LINK_RETRY_WINDOW_MINUTES = 30

// Cadence of the page's own runs-window poll (matches the fleet section's); retries cold/failed loads.
const RUNS_REFETCH_INTERVAL_MS = 60_000

export type FindingsSortKey = 'newest' | 'oldest' | 'severity' | 'confidence'
export const FINDINGS_SCOUT_FILTER_ALL = 'all'
export const FINDINGS_SEVERITY_FILTER_ALL = 'all'

/** Lowest number = most severe, so the severity sort is a plain ascending compare. Null sinks last. */
const SEVERITY_RANK: Record<SignalReportPriority, number> = { P0: 0, P1: 1, P2: 2, P3: 3, P4: 4 }
function severityRank(severity: SignalReportPriority | null): number {
    return severity == null ? 5 : SEVERITY_RANK[severity]
}

/**
 * Fleet-wide findings logic — the cross-troop counterpart of the per-scout `scoutDetailLogic`. Reuses
 * `scoutFleetLogic`'s polled runs window to find every scout's recent emitted runs, fetches each run's
 * emissions + report links, and flattens them into one searchable/filterable/sortable list. Singleton,
 * mounted only by the findings page, so the per-run fan-out stays lazy (the callout reads the cheap
 * `scoutFleetLogic.emittedFindingsSummary` instead).
 */
export const findingsLogic = kea<findingsLogicType>([
    path(['scenes', 'inbox', 'logics', 'findingsLogic']),

    connect(() => ({
        values: [scoutFleetLogic, ['runsWindow', 'runsWindowLoadedOnce', 'runsWindowComplete']],
    })),

    actions({
        setSearchText: (searchText: string) => ({ searchText }),
        setScoutFilter: (scoutFilter: string) => ({ scoutFilter }),
        setSeverityFilter: (severityFilter: string) => ({ severityFilter }),
        setSortKey: (sortKey: FindingsSortKey) => ({ sortKey }),
        // Some (but not all) per-run emission fetches failed — the list is incomplete. Carries the
        // failed-run count so the page can warn that findings are missing rather than hiding it.
        setEmissionsPartialFailure: (failedRuns: number) => ({ failedRuns }),
    }),

    loaders(({ values, actions }) => ({
        emissions: [
            [] as SignalScoutEmission[],
            {
                loadEmissions: async () => {
                    const runs = values.emittedRuns
                    if (runs.length === 0) {
                        return []
                    }
                    // allSettled, not all: one failed run's fetch shouldn't discard every other run's
                    // findings — surface the partial set.
                    const settled = await Promise.allSettled(
                        runs.map((run) => api.signalScout.runs.emissions(run.run_id))
                    )
                    const fulfilled = settled.filter(
                        (result): result is PromiseFulfilledResult<SignalScoutEmission[]> =>
                            result.status === 'fulfilled'
                    )
                    // All fetches failed while the runs say these emitted — throw so the page shows an
                    // error, not a false "no findings".
                    if (fulfilled.length === 0) {
                        throw new Error('Failed to load scout findings')
                    }
                    // A partial failure returns the findings that loaded, but flag the gap so the page
                    // can warn — silently dropping a scout's findings would mislead a triage decision.
                    actions.setEmissionsPartialFailure(settled.length - fulfilled.length)
                    return fulfilled.flatMap((result) => result.value)
                },
            },
        ],
        emissionReports: [
            [] as SignalScoutEmissionReportLink[],
            {
                loadEmissionReports: async () => {
                    const runs = values.emittedRuns
                    if (runs.length === 0) {
                        return []
                    }
                    // Retain the prior round's links for a failed run (this re-runs on the poll); its
                    // links are the ones whose source_id is prefixed `run:<run_id>:`.
                    const previous = values.emissionReports
                    const settled = await Promise.allSettled(
                        runs.map((run) => api.signalScout.runs.emissionReports(run.run_id))
                    )
                    return runs.flatMap((run, index) => {
                        const result = settled[index]
                        if (result.status === 'fulfilled') {
                            return result.value
                        }
                        const prefix = `run:${run.run_id}:`
                        return previous.filter((link) => link.source_id.startsWith(prefix))
                    })
                },
            },
        ],
    })),

    reducers({
        searchText: ['', { setSearchText: (_, { searchText }) => searchText }],
        scoutFilter: [FINDINGS_SCOUT_FILTER_ALL as string, { setScoutFilter: (_, { scoutFilter }) => scoutFilter }],
        severityFilter: [
            FINDINGS_SEVERITY_FILTER_ALL as string,
            { setSeverityFilter: (_, { severityFilter }) => severityFilter },
        ],
        sortKey: ['newest' as FindingsSortKey, { setSortKey: (_, { sortKey }) => sortKey }],
        // True only when the most recent emissions load failed outright (all per-run fetches rejected).
        emissionsLoadFailed: [
            false,
            {
                loadEmissions: () => false,
                loadEmissionsSuccess: () => false,
                loadEmissionsFailure: () => true,
            },
        ],
        // Count of runs whose emission fetch failed while others succeeded — the list is incomplete.
        // Reset when a fresh load starts; a clean success sets it to 0 via the partial-failure action.
        emissionsPartialFailedRuns: [
            0,
            {
                loadEmissions: () => 0,
                loadEmissionsFailure: () => 0,
                setEmissionsPartialFailure: (_, { failedRuns }) => failedRuns,
            },
        ],
    }),

    selectors({
        // Emitted runs newest-first, capped fleet-wide. Shares `mostRecentEmittedRuns` with the callout
        // summary so the two count the exact same run set.
        emittedRuns: [
            (s) => [s.runsWindow],
            (runsWindow: { runs: SignalScoutRunSummary[]; complete: boolean }): SignalScoutRunSummary[] =>
                mostRecentEmittedRuns(runsWindow.runs),
        ],
        // Stable key over the emitted runs — refetch only when the set changes, not on every poll.
        // Includes `emitted_count` so an in-progress run that emits more findings retriggers.
        emittedRunsKey: [
            (s) => [s.emittedRuns],
            (emittedRuns: SignalScoutRunSummary[]): string =>
                emittedRuns
                    .map((run) => `${run.run_id}:${run.emitted_count ?? 0}`)
                    .sort()
                    .join(','),
        ],
        reportBySourceId: [
            (s) => [s.emissionReports],
            (emissionReports): Map<string, LinkedSignalReport> =>
                new Map(
                    emissionReports
                        .filter((link) => link.report !== null)
                        .map((link) => [link.source_id, link.report as LinkedSignalReport])
                ),
        ],
        // Join emissions back to their run (for skill_name + task-run link) and the report they grouped into.
        rows: [
            (s) => [s.emissions, s.emittedRuns, s.reportBySourceId],
            (
                emissions: SignalScoutEmission[],
                emittedRuns: SignalScoutRunSummary[],
                reportBySourceId: Map<string, LinkedSignalReport>
            ): ScoutEmissionRow[] => {
                const runsById = new Map(emittedRuns.map((run) => [run.run_id, run]))
                return emissions
                    .map((emission) => {
                        const run = runsById.get(emission.run_id)
                        return run ? { emission, run, report: reportBySourceId.get(emission.source_id) ?? null } : null
                    })
                    .filter((row): row is ScoutEmissionRow => row !== null)
            },
        ],
        // Distinct scouts present in the loaded findings, with a per-scout count, for the scout filter.
        availableScouts: [
            (s) => [s.rows],
            (rows): { skillName: string; label: string; count: number }[] => {
                const counts = new Map<string, number>()
                for (const row of rows) {
                    counts.set(row.run.skill_name, (counts.get(row.run.skill_name) ?? 0) + 1)
                }
                return [...counts.entries()]
                    .map(([skillName, count]) => ({ skillName, label: prettifyScoutSkillName(skillName), count }))
                    .sort((a, b) => a.label.localeCompare(b.label))
            },
        ],
        // Visible set: search (over finding text + prettified scout name) + scout + severity, then sort.
        filteredRows: [
            (s) => [s.rows, s.searchText, s.scoutFilter, s.severityFilter, s.sortKey],
            (rows, searchText, scoutFilter, severityFilter, sortKey): ScoutEmissionRow[] => {
                const needle = searchText.trim().toLowerCase()
                const filtered = rows.filter((row) => {
                    if (scoutFilter !== FINDINGS_SCOUT_FILTER_ALL && row.run.skill_name !== scoutFilter) {
                        return false
                    }
                    if (severityFilter !== FINDINGS_SEVERITY_FILTER_ALL && row.emission.severity !== severityFilter) {
                        return false
                    }
                    if (needle) {
                        const haystack = `${row.emission.description ?? ''} ${prettifyScoutSkillName(
                            row.run.skill_name
                        )}`.toLowerCase()
                        if (!haystack.includes(needle)) {
                            return false
                        }
                    }
                    return true
                })
                const byNewest = (a: ScoutEmissionRow, b: ScoutEmissionRow): number =>
                    (b.emission.emitted_at ?? '').localeCompare(a.emission.emitted_at ?? '')
                return filtered.slice().sort((a, b) => {
                    if (sortKey === 'oldest') {
                        return -byNewest(a, b)
                    }
                    if (sortKey === 'severity') {
                        const diff = severityRank(a.emission.severity) - severityRank(b.emission.severity)
                        return diff !== 0 ? diff : byNewest(a, b)
                    }
                    if (sortKey === 'confidence') {
                        const diff = (b.emission.confidence ?? 0) - (a.emission.confidence ?? 0)
                        return diff !== 0 ? diff : byNewest(a, b)
                    }
                    return byNewest(a, b)
                })
            },
        ],
        // Page header tallies, from the loaded set (not the cheap window sum the callout uses).
        totalCount: [(s) => [s.rows], (rows): number => rows.length],
        scoutCount: [(s) => [s.availableScouts], (availableScouts): number => availableScouts.length],
        latestEmittedAt: [
            (s) => [s.rows],
            (rows): string | null => {
                let latest: string | null = null
                for (const row of rows) {
                    const at = row.emission.emitted_at
                    if (at && (!latest || at > latest)) {
                        latest = at
                    }
                }
                return latest
            },
        ],
        // "Loaded once" — distinguishes "not loaded yet" from "loaded, empty" without a skeleton flash.
        // With no emitted runs there's nothing to fetch, so resolve immediately; otherwise the
        // `!emissionsLoading` guard suppresses poll flicker once findings are in hand.
        hasLoadedOnce: [
            (s) => [s.runsWindowLoadedOnce, s.emittedRuns, s.emissionsLoading, s.emissions],
            (runsWindowLoadedOnce, emittedRuns: SignalScoutRunSummary[], emissionsLoading, emissions): boolean =>
                runsWindowLoadedOnce && (emittedRuns.length === 0 || !emissionsLoading || emissions.length > 0),
        ],
    }),

    subscriptions(({ actions }) => ({
        // Fires on mount and whenever the emitted-run set changes; the key holds equal across no-op polls.
        emittedRunsKey: () => {
            actions.loadEmissions()
            actions.loadEmissionReports()
        },
    })),

    listeners(({ actions, values }) => ({
        // Ride the fleet's runs-window poll to refetch report links while a recent finding is unlinked.
        [scoutFleetLogic.actionTypes.loadRunsWindowSuccess]: () => {
            const cutoff = dayjs().subtract(REPORT_LINK_RETRY_WINDOW_MINUTES, 'minute')
            const hasRecentUnlinked = values.rows.some(
                (row) =>
                    row.report === null && row.emission.emitted_at && dayjs(row.emission.emitted_at).isAfter(cutoff)
            )
            if (hasRecentUnlinked) {
                actions.loadEmissionReports()
            }
        },
    })),

    events(({ cache }) => ({
        afterMount: () => {
            // The page can be reached cold (shared URL, or narrow viewport with no rail) when the fleet
            // section that normally polls the runs window isn't mounted. Own a poll here so the page
            // loads, *retries* a failed initial load (else `hasLoadedOnce` would never flip), and gives
            // the report-link retry listener a poll to ride. It lives on this logic's own disposables
            // under its own key, so it never disposes the section's `runsPoll` — when both are mounted
            // the overlap just costs one extra capped request, since `loadRunsWindow` is idempotent.
            scoutFleetLogic.actions.loadRunsWindow()
            cache.disposables.add(() => {
                const interval = setInterval(() => scoutFleetLogic.actions.loadRunsWindow(), RUNS_REFETCH_INTERVAL_MS)
                return () => clearInterval(interval)
            }, 'findingsRunsPoll')
        },
    })),
])

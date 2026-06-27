import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
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
import { prettifyScoutSkillName } from '../utils/scoutRunsWindow'
import type { findingsLogicType } from './findingsLogicType'
import { ScoutEmissionRow } from './scoutDetailLogic'
import { scoutFleetLogic } from './scoutFleetLogic'

// Fleet-wide the fan-out is larger than a single scout's page, so bound the fetched window harder:
// the most recent emitted runs across the whole troop. Older findings live on in the inbox reports
// they produced. Sized to keep the concurrent emission fetches (and rendered cards) reasonable.
const MAX_FLEET_EMITTED_RUNS = 120

// Report linkage is eventually consistent (a finding's signal groups into a report asynchronously),
// so keep retrying the reverse lookup on the fleet's runs-window poll, but only while a *recent*
// finding is still unlinked — past this it'll never group (deduped, deleted, below threshold).
const REPORT_LINK_RETRY_WINDOW_MINUTES = 30

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
 * the singleton `scoutFleetLogic`'s already-polled runs window to find every scout's recent emitted
 * runs, fetches each run's emissions + report links, and flattens them into one searchable,
 * filterable, sortable list. Singleton (not keyed): mounted only by the findings page, so the per-run
 * emission fan-out stays lazy — the fleet section's callout reads the cheap
 * `scoutFleetLogic.emittedFindingsSummary` instead.
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
    }),

    loaders(({ values }) => ({
        emissions: [
            [] as SignalScoutEmission[],
            {
                loadEmissions: async () => {
                    const runs = values.emittedRuns
                    if (runs.length === 0) {
                        return []
                    }
                    // allSettled, not all: one failed run's fetch (transient 500, deleted run) shouldn't
                    // discard every other run's findings — surface the partial set.
                    const settled = await Promise.allSettled(
                        runs.map((run) => api.signalScout.runs.emissions(run.run_id))
                    )
                    const fulfilled = settled.filter(
                        (result): result is PromiseFulfilledResult<SignalScoutEmission[]> =>
                            result.status === 'fulfilled'
                    )
                    // Every fetch failed (outage / auth / scope) while the runs say these emitted —
                    // throw so the page shows an error, not a false "no findings". A partial failure
                    // still returns the findings that did load.
                    if (fulfilled.length === 0) {
                        throw new Error('Failed to load scout findings')
                    }
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
                    // Retain the prior round's links per run on failure (this loader re-runs on the poll):
                    // source_id is `run:<run_id>:finding:<id>`, so a failed run's already-resolved chips
                    // are the ones prefixed with its run_id.
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
    }),

    selectors({
        // Every scout's runs that emitted at least one finding, newest first, capped fleet-wide.
        emittedRuns: [
            (s) => [s.runsWindow],
            (runsWindow: { runs: SignalScoutRunSummary[]; complete: boolean }): SignalScoutRunSummary[] =>
                runsWindow.runs
                    .filter((run) => (run.emitted_count ?? 0) > 0)
                    .slice()
                    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
                    .slice(0, MAX_FLEET_EMITTED_RUNS),
        ],
        // Stable string key over the emitted runs — refetch only when the set actually changes, not on
        // every 60s runs-window poll. Includes `emitted_count` so an in-progress run that emits more
        // findings retriggers.
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
        // Join fetched emissions back to their run (carries skill_name + the task-run link) and to the
        // inbox report they grouped into.
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
        // The visible set: search + scout + severity filters, then the chosen sort. Search matches the
        // finding text and the (prettified) scout name, so typing a scout name narrows too.
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
        // "Loaded once" so the page tells "not loaded yet" from "loaded, genuinely empty" without
        // flickering a skeleton on the 60s poll. When the window loaded but no run emitted anything
        // there's nothing to fetch, so we're done immediately — otherwise the no-op `loadEmissions([])`
        // would flash skeletons for a tick before the empty state. The `!emissionsLoading` guard then
        // only governs the has-emissions case (suppressing poll flicker once findings are in hand).
        hasLoadedOnce: [
            (s) => [s.runsWindowLoadedOnce, s.emittedRuns, s.emissionsLoading, s.emissions],
            (runsWindowLoadedOnce, emittedRuns: SignalScoutRunSummary[], emissionsLoading, emissions): boolean =>
                runsWindowLoadedOnce && (emittedRuns.length === 0 || !emissionsLoading || emissions.length > 0),
        ],
    }),

    subscriptions(({ actions }) => ({
        // Fires on mount (empty → real ids once the runs window loads) and whenever the emitted-run set
        // changes; the string key holds equal across no-op polls so we don't refetch.
        emittedRunsKey: () => {
            actions.loadEmissions()
            actions.loadEmissionReports()
        },
    })),

    listeners(({ actions, values }) => ({
        // Report grouping resolves asynchronously, so ride the fleet's 60s runs-window poll to keep
        // refetching the links — but only while a recently-emitted finding is still unlinked.
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
])

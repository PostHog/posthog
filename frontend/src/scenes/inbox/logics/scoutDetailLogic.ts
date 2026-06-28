import { connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import {
    LinkedSignalReport,
    SignalReport,
    SignalScoutEmission,
    SignalScoutEmissionReportLink,
    SignalScoutRunSummary,
} from '../types'
import type { scoutDetailLogicType } from './scoutDetailLogicType'
import { scoutFleetLogic } from './scoutFleetLogic'

export interface ScoutDetailLogicProps {
    skillName: string
}

/** How a scout touched a report through the report channel: authored it (`emit_report`) or only edited
 * an existing one (`edit_report`). Authoring supersedes a later edit of the same report. */
export type ScoutReportAction = 'authored' | 'edited'

/** A report this scout authored or edited in the window, paired with how it touched it. */
export interface ScoutReportRow {
    report: SignalReport
    action: ScoutReportAction
}

// A report-authoring scout could in theory touch many reports across the window; bound the per-report
// fetch fan-out the same way emissions are bounded.
const MAX_TOUCHED_REPORTS = 50

// A noisy scout on the 30-minute floor can rack up hundreds of emitted runs across the window;
// fetching emissions for all of them at once would fan out hundreds of concurrent requests and
// render hundreds of markdown cards. Bound both to the most recent N emitted runs — older
// findings live on in the inbox reports they produced.
const MAX_EMITTED_RUNS = 50

// Report linkage is eventually consistent: a finding's signal is grouped into a report asynchronously
// after the run emits it, so the reverse lookup can return `report: null` right after emission and
// resolve minutes later. The emissions themselves are stable once a run completes, so the
// `emittedRunsKey` subscription never refires for them — but the report links need to keep retrying.
// We re-fetch them on the fleet's existing 60s runs-window poll, but only while a *recent* finding is
// still unlinked. Past this window the remaining nulls are findings that will never group (deduped,
// deleted, or below the report threshold), so we stop polling for them.
const REPORT_LINK_RETRY_WINDOW_MINUTES = 30

/** An emitted finding paired with the run that produced it (for the run-level task link) and the
 * inbox report its signal grouped into, if any (for the "In report" deep-link chip). */
export interface ScoutEmissionRow {
    emission: SignalScoutEmission
    run: SignalScoutRunSummary
    report: LinkedSignalReport | null
}

/**
 * Per-scout detail logic, keyed by skill_name. Reuses the singleton `scoutFleetLogic`'s
 * runs window (already polled while the detail page is open) to find this scout's emitted
 * runs, then fetches each run's emissions and flattens them into one newest-first list — the
 * Signals section. The runs endpoint has no per-finding listing, so emissions are fetched
 * per emitted run; quiet runs (the vast majority) are never hit.
 */
export const scoutDetailLogic = kea<scoutDetailLogicType>([
    path((key) => ['scenes', 'inbox', 'logics', 'scoutDetailLogic', key]),
    props({} as ScoutDetailLogicProps),
    key((props) => props.skillName),

    connect(() => ({
        values: [scoutFleetLogic, ['rollups', 'runsWindowLoadedOnce', 'runsWindowComplete']],
    })),

    loaders(({ values }) => ({
        emissions: [
            [] as SignalScoutEmission[],
            {
                loadEmissions: async () => {
                    const runs = values.emittedRuns
                    if (runs.length === 0) {
                        return []
                    }
                    // allSettled, not all: one failed run's fetch (transient 500, deleted run)
                    // shouldn't discard every other run's findings — surface the partial set.
                    const settled = await Promise.allSettled(
                        runs.map((run) => api.signalScout.runs.emissions(run.run_id))
                    )
                    const fulfilled = settled.filter(
                        (result): result is PromiseFulfilledResult<SignalScoutEmission[]> =>
                            result.status === 'fulfilled'
                    )
                    // Every fetch failed (outage / auth / scope) while the rollup says these runs
                    // emitted — throw so the section shows an error, not a false "no signals". A
                    // partial failure still returns the findings that did load.
                    if (fulfilled.length === 0) {
                        throw new Error('Failed to load scout emissions')
                    }
                    return fulfilled.flatMap((result) => result.value)
                },
            },
        ],
        // The reverse "which inbox report did this finding land in" lookup, fetched per emitted run
        // off the same window as the emissions themselves. Best-effort and non-blocking: a finding
        // with no resolved report (not yet grouped, deduped, deleted) simply gets no chip, and a
        // failed fetch leaves the cards as-is rather than erroring the whole section.
        emissionReports: [
            [] as SignalScoutEmissionReportLink[],
            {
                loadEmissionReports: async () => {
                    const runs = values.emittedRuns
                    if (runs.length === 0) {
                        return []
                    }
                    // Retains the prior round's links per run on failure: this loader is re-run by the
                    // runs-window poll, so blindly keeping only the fulfilled responses would drop a
                    // failed run's already-resolved chips (and an all-rejected retry would clear them
                    // all). source_id is `run:<run_id>:finding:<id>`, so prior links for a run are the
                    // ones prefixed with its run_id.
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
        // The reports this scout authored/edited directly via the report channel. Unlike findings, the run
        // already carries the report id (no async grouping), so this fetches each report straight by id to
        // resolve its title + live status for the Reports section. Best-effort: a deleted/inaccessible
        // report drops out (its `get` rejects) rather than erroring the section.
        scoutReports: [
            [] as SignalReport[],
            {
                loadScoutReports: async () => {
                    const touched = values.touchedReports.slice(0, MAX_TOUCHED_REPORTS)
                    if (touched.length === 0) {
                        return []
                    }
                    const settled = await Promise.allSettled(touched.map(({ id }) => api.signalReports.get(id)))
                    return settled
                        .filter(
                            (result): result is PromiseFulfilledResult<SignalReport> => result.status === 'fulfilled'
                        )
                        .map((result) => result.value)
                },
            },
        ],
    })),

    reducers({
        // True only when the most recent emissions load failed outright (all per-run fetches
        // rejected). Reset when a fresh load starts or succeeds. Lets the Signals section show a
        // retrying/error state instead of a false empty when findings exist but couldn't be loaded.
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
        // This scout's runs that emitted at least one finding, newest first, capped to the most
        // recent MAX_EMITTED_RUNS. `.filter()` returns a fresh array, so the in-place `.sort()`
        // never touches the shared rollup `runs` the header timeline reads (oldest-first).
        emittedRuns: [
            (s) => [s.rollups, (_, props) => props.skillName],
            (rollups, skillName): SignalScoutRunSummary[] =>
                (rollups.get(skillName)?.runs ?? [])
                    .filter((run) => (run.emitted_count ?? 0) > 0)
                    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
                    .slice(0, MAX_EMITTED_RUNS),
        ],
        // Stable string key over the emitted runs — refetch emissions only when the set actually
        // changes, not on every 60s runs-window poll that returns the same runs. Includes
        // `emitted_count` so a run that emits more findings while still in progress retriggers.
        emittedRunsKey: [
            (s) => [s.emittedRuns],
            (emittedRuns): string =>
                emittedRuns
                    .map((run) => `${run.run_id}:${run.emitted_count ?? 0}`)
                    .sort()
                    .join(','),
        ],
        // source_id -> linked inbox report, for findings that resolved to one. Keyed on source_id
        // (the deterministic `run:<run_id>:finding:<id>` join), which is unique per emission and the
        // exact field the backend reverse-lookup keys on. Findings with a null report are skipped.
        reportBySourceId: [
            (s) => [s.emissionReports],
            (emissionReports): Map<string, LinkedSignalReport> =>
                new Map(
                    emissionReports
                        .filter((link) => link.report !== null)
                        .map((link) => [link.source_id, link.report as LinkedSignalReport])
                ),
        ],
        // The distinct reports this scout touched via the report channel in the window, each tagged with
        // how it touched it. Read off the rollup's deduped id sets; authoring supersedes a later edit of
        // the same report, so a report in both sets reads as "authored".
        touchedReports: [
            (s) => [s.rollups, (_, props) => props.skillName],
            (rollups, skillName): { id: string; action: ScoutReportAction }[] => {
                const rollup = rollups.get(skillName)
                if (!rollup) {
                    return []
                }
                const byId = new Map<string, ScoutReportAction>()
                for (const id of rollup.editedReportIds) {
                    byId.set(id, 'edited')
                }
                for (const id of rollup.authoredReportIds) {
                    byId.set(id, 'authored')
                }
                return [...byId.entries()].map(([id, action]) => ({ id, action }))
            },
        ],
        // Stable key over the touched report set — refetch the reports only when the set actually changes,
        // not on every runs-window poll that returns the same runs.
        touchedReportsKey: [
            (s) => [s.touchedReports],
            (touchedReports): string =>
                touchedReports
                    .map(({ id, action }) => `${id}:${action}`)
                    .sort()
                    .join(','),
        ],
        // Join the fetched reports back to how the scout touched each, newest-updated first. A touched id
        // whose report fetch failed (deleted/inaccessible) is skipped.
        reportRows: [
            (s) => [s.scoutReports, s.touchedReports],
            (scoutReports, touchedReports): ScoutReportRow[] => {
                const actionById = new Map(touchedReports.map(({ id, action }) => [id, action]))
                return scoutReports
                    .map((report) => {
                        const action = actionById.get(report.id)
                        return action ? { report, action } : null
                    })
                    .filter((row): row is ScoutReportRow => row !== null)
                    .sort((a, b) => (b.report.updated_at ?? '').localeCompare(a.report.updated_at ?? ''))
            },
        ],
        // Join fetched emissions back to their run (for the per-row task-run link) and to the inbox
        // report they grouped into (for the "In report" chip), newest first.
        emissionRows: [
            (s) => [s.emissions, s.emittedRuns, s.reportBySourceId],
            (emissions, emittedRuns, reportBySourceId): ScoutEmissionRow[] => {
                const runsById = new Map(emittedRuns.map((run) => [run.run_id, run]))
                return emissions
                    .map((emission) => {
                        const run = runsById.get(emission.run_id)
                        return run ? { emission, run, report: reportBySourceId.get(emission.source_id) ?? null } : null
                    })
                    .filter((row): row is ScoutEmissionRow => row !== null)
                    .sort((a, b) => (b.emission.emitted_at ?? '').localeCompare(a.emission.emitted_at ?? ''))
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        // Fires on mount (empty → real ids once the runs window loads) and whenever the set of
        // emitted runs changes; the string key holds equal across no-op polls so we don't refetch.
        emittedRunsKey: () => {
            actions.loadEmissions()
            actions.loadEmissionReports()
        },
        // Fires on mount (empty → real ids once the runs window loads) and whenever the set of touched
        // reports changes; the key holds equal across no-op polls so we don't refetch.
        touchedReportsKey: () => {
            actions.loadScoutReports()
        },
    })),

    listeners(({ actions, values }) => ({
        // Report grouping resolves asynchronously after emission, so ride the fleet's 60s runs-window
        // poll to keep refetching the links — but only while a recently-emitted finding is still
        // unlinked. Computed fresh here (not a memoized selector) so the recency cutoff advances with
        // wall-clock time and a never-grouping finding stops the poll once it ages out of the window.
        [scoutFleetLogic.actionTypes.loadRunsWindowSuccess]: () => {
            const cutoff = dayjs().subtract(REPORT_LINK_RETRY_WINDOW_MINUTES, 'minute')
            const hasRecentUnlinked = values.emissionRows.some(
                (row) =>
                    row.report === null && row.emission.emitted_at && dayjs(row.emission.emitted_at).isAfter(cutoff)
            )
            if (hasRecentUnlinked) {
                actions.loadEmissionReports()
            }
        },
    })),
])

import { connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'

import { SignalScoutEmission, SignalScoutRunSummary } from '../types'
import type { scoutDetailLogicType } from './scoutDetailLogicType'
import { scoutFleetLogic } from './scoutFleetLogic'

export interface ScoutDetailLogicProps {
    skillName: string
}

/** An emitted finding paired with the run that produced it (for the run-level task link). */
export interface ScoutEmissionRow {
    emission: SignalScoutEmission
    run: SignalScoutRunSummary
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
        values: [scoutFleetLogic, ['rollups']],
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
                    const perRun = await Promise.all(runs.map((run) => api.signalScout.runs.emissions(run.run_id)))
                    return perRun.flat()
                },
            },
        ],
    })),

    selectors({
        // This scout's runs that emitted at least one finding, newest first.
        emittedRuns: [
            (s) => [s.rollups, (_, props) => props.skillName],
            (rollups, skillName): SignalScoutRunSummary[] =>
                (rollups.get(skillName)?.runs ?? [])
                    .filter((run) => (run.emitted_count ?? 0) > 0)
                    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '')),
        ],
        // Stable string key over the emitted run ids — refetch emissions only when the set
        // actually changes, not on every 60s runs-window poll that returns the same runs.
        emittedRunsKey: [
            (s) => [s.emittedRuns],
            (emittedRuns): string =>
                emittedRuns
                    .map((run) => run.run_id)
                    .sort()
                    .join(','),
        ],
        // Join fetched emissions back to their run (for the per-row task-run link), newest first.
        emissionRows: [
            (s) => [s.emissions, s.emittedRuns],
            (emissions, emittedRuns): ScoutEmissionRow[] => {
                const runsById = new Map(emittedRuns.map((run) => [run.run_id, run]))
                return emissions
                    .map((emission) => {
                        const run = runsById.get(emission.run_id)
                        return run ? { emission, run } : null
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
        },
    })),
])

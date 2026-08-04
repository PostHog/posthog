import { ExperimentFlagKeysManager } from '~/ingestion/common/flag-evaluations/experiment-flag-keys-manager'
import { experimentFlagKeysLookupTotal } from '~/ingestion/common/flag-evaluations/metrics'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { PipelineEvent, Team } from '~/types'

export type MeasureExperimentFlagKeysStepInput = { event: PipelineEvent; team: Team }

/** Per team, how many events in the chunk referenced each flag key. */
type FlagCountsByTeam = Map<number, Map<string, number>>

/**
 * Records whether each $feature_flag_called event's flag has a live experiment,
 * through the same cache the routing fork will consult once it lands. Nothing acts
 * on the answer yet, so the purpose is to measure the query cost and the answer
 * distribution against production traffic before a routing decision depends on
 * either. Passing no manager disables it.
 *
 * One batched lookup per chunk, keyed by team, but counted once per event: the
 * answer is per-flag, while the distribution worth measuring is per-event, since
 * that is the traffic the fork would reroute.
 *
 * Fire-and-forget, so it adds no latency to the chunk. Rejections are swallowed
 * because the manager throws so that a real consumer can fail toward not routing,
 * and there is no consumer here to protect: an unhandled rejection would restart
 * the worker over a measurement.
 */
export function createMeasureExperimentFlagKeysStep<T extends MeasureExperimentFlagKeysStepInput>(
    experimentFlagKeysManager?: ExperimentFlagKeysManager
) {
    return function measureExperimentFlagKeysStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (experimentFlagKeysManager) {
            const flagCounts: FlagCountsByTeam = new Map()
            for (const { event, team } of events) {
                if (event.event !== '$feature_flag_called') {
                    continue
                }
                const flagKey = event.properties?.['$feature_flag']
                if (typeof flagKey !== 'string') {
                    continue
                }
                let countsForTeam = flagCounts.get(team.id)
                if (!countsForTeam) {
                    countsForTeam = new Map()
                    flagCounts.set(team.id, countsForTeam)
                }
                countsForTeam.set(flagKey, (countsForTeam.get(flagKey) ?? 0) + 1)
            }
            if (flagCounts.size > 0) {
                void recordLookups(experimentFlagKeysManager, flagCounts).catch(() => {})
            }
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}

async function recordLookups(
    experimentFlagKeysManager: ExperimentFlagKeysManager,
    flagCounts: FlagCountsByTeam
): Promise<void> {
    const keysByTeam = await experimentFlagKeysManager.getExperimentFlagKeys([...flagCounts.keys()])

    let hasExperiment = 0
    let noExperiment = 0
    for (const [teamId, countsForTeam] of flagCounts) {
        const experimentFlagKeys = keysByTeam[String(teamId)]
        for (const [flagKey, count] of countsForTeam) {
            if (experimentFlagKeys?.has(flagKey)) {
                hasExperiment += count
            } else {
                noExperiment += count
            }
        }
    }

    if (hasExperiment > 0) {
        experimentFlagKeysLookupTotal.labels('has_experiment').inc(hasExperiment)
    }
    if (noExperiment > 0) {
        experimentFlagKeysLookupTotal.labels('no_experiment').inc(noExperiment)
    }
}

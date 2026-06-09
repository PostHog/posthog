import { PluginEvent } from '~/plugin-scaffold'

import { Team } from '../../types'
import { PipelineResult, drop, ok } from '../pipelines/results'
import {
    FeatureFlagCalledDedupService,
    featureFlagCalledDedupKey,
} from '../utils/feature-flag-called-dedup/feature-flag-called-dedup-service'
import { featureFlagCalledDedupEventsTotal } from '../utils/feature-flag-called-dedup/metrics'

export interface DedupeFeatureFlagCalledStepInput {
    event: PluginEvent
    team: Team
}

/**
 * Drops redundant $feature_flag_called events using a keep-first Redis claim
 * keyed on (team, distinct_id, flag, response, groups). Server-side SDKs on
 * multi-process fleets re-emit the same exposure from every worker; only the
 * first copy carries signal, so the survivors preserve experiment exposure
 * and last_called_at semantics while the bulk of the volume is dropped.
 *
 * Must run after cookieless processing (which rewrites event.distinct_id) and
 * before person processing, so dropped events skip the person and ClickHouse
 * writes entirely.
 *
 * In 'shadow' mode the claim is made and counted but nothing is dropped. If no
 * service is provided or the mode is 'disabled', this step is a passthrough.
 * Redis failures fail open inside the service: every event passes.
 */
export function createDedupeFeatureFlagCalledStep<T extends DedupeFeatureFlagCalledStepInput>(
    dedupService?: FeatureFlagCalledDedupService
) {
    return async function dedupeFeatureFlagCalledStep(inputs: T[]): Promise<PipelineResult<T>[]> {
        if (!dedupService || dedupService.mode === 'disabled' || inputs.length === 0) {
            return inputs.map((input) => ok(input))
        }

        const keyPerInput: (string | null)[] = inputs.map((input) => {
            if (input.event.event !== '$feature_flag_called' || !dedupService.isEnabledForTeam(input.team.id)) {
                return null
            }
            const properties = input.event.properties ?? {}
            const flagKey = properties['$feature_flag']
            if (typeof flagKey !== 'string') {
                return null
            }
            return featureFlagCalledDedupKey(
                input.team.id,
                input.event.distinct_id,
                flagKey,
                properties['$feature_flag_response'],
                properties['$groups']
            )
        })

        const keys = keyPerInput.filter((key): key is string => key !== null)
        if (keys.length === 0) {
            return inputs.map((input) => ok(input))
        }

        const claimed = await dedupService.claimKeys(keys)

        let cursor = 0
        return inputs.map((input, index) => {
            if (keyPerInput[index] === null) {
                return ok(input)
            }
            const isFirst = claimed[cursor++]
            if (isFirst) {
                featureFlagCalledDedupEventsTotal.labels('first_seen').inc()
                return ok(input)
            }
            if (dedupService.mode === 'drop') {
                featureFlagCalledDedupEventsTotal.labels('duplicate_dropped').inc()
                return drop('feature_flag_called_duplicate')
            }
            featureFlagCalledDedupEventsTotal.labels('duplicate_shadow').inc()
            return ok(input)
        })
    }
}

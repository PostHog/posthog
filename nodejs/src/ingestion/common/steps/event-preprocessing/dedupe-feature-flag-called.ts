import {
    FeatureFlagCalledDedupClaim,
    FeatureFlagCalledDedupService,
    featureFlagCalledDedupKey,
} from '~/ingestion/common/feature-flag-called-dedup/feature-flag-called-dedup-service'
import { featureFlagCalledDedupEventsTotal } from '~/ingestion/common/feature-flag-called-dedup/metrics'
import { PipelineResult, drop, ok } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { Team } from '~/types'

export interface DedupeFeatureFlagCalledStepInput {
    event: PluginEvent
    team: Team
}

/**
 * Drops redundant $feature_flag_called events using a keep-first Redis claim
 * keyed on (team, distinct_id, flag, response, groups, has_experiment).
 * Server-side SDKs on multi-process fleets re-emit the same exposure from every
 * worker; only the first copy carries signal, so the survivors preserve
 * experiment exposure semantics while the bulk of the volume is dropped.
 * Note that "last called" timestamps become TTL-granular: within a dedup
 * window they reflect the first call, not the most recent one.
 *
 * Claims are tagged with the event uuid, so a batch replayed by at-least-once
 * Kafka delivery recognizes its own claims from a failed prior attempt
 * instead of dropping events that were never written.
 *
 * Must run after cookieless processing (which rewrites event.distinct_id) and
 * before person processing, so dropped events skip the person and ClickHouse
 * writes entirely.
 *
 * In 'shadow' mode the claim is made and counted but nothing is dropped. If no
 * service is provided, this step is a passthrough. Redis failures fail open
 * inside the service: every event passes.
 */
export function createDedupeFeatureFlagCalledStep<T extends DedupeFeatureFlagCalledStepInput>(
    dedupService?: FeatureFlagCalledDedupService
) {
    return async function dedupeFeatureFlagCalledStep(inputs: T[]): Promise<PipelineResult<T>[]> {
        if (!dedupService || inputs.length === 0) {
            return inputs.map((input) => ok(input))
        }

        const claimPerInput: (FeatureFlagCalledDedupClaim | null)[] = inputs.map((input) => {
            if (input.event.event !== '$feature_flag_called' || !dedupService.isEnabledForTeam(input.team.id)) {
                return null
            }
            const properties = input.event.properties ?? {}
            const flagKey = properties['$feature_flag']
            // Without a uuid there is no stable claim identity, so pass the event through.
            if (typeof flagKey !== 'string' || !input.event.uuid) {
                return null
            }
            return {
                key: featureFlagCalledDedupKey(
                    input.team.id,
                    input.event.distinct_id,
                    flagKey,
                    properties['$feature_flag_response'],
                    properties['$groups'],
                    properties['$feature_flag_has_experiment']
                ),
                claimId: input.event.uuid,
            }
        })

        const claims = claimPerInput.filter((claim): claim is FeatureFlagCalledDedupClaim => claim !== null)
        if (claims.length === 0) {
            return inputs.map((input) => ok(input))
        }

        const claimed = await dedupService.claimKeys(claims)

        // `claimed` has exactly one entry per non-null claim, in input order.
        // A missing entry fails open: a short result must never drop events.
        let claimIndex = 0
        return inputs.map((input, index) => {
            if (claimPerInput[index] === null) {
                return ok(input)
            }
            const isFirst = claimed[claimIndex++] ?? true
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

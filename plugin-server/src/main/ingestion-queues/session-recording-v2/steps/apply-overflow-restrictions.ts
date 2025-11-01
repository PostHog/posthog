import { PipelineResult, ok, redirect } from '../../../../ingestion/pipelines/results'
import { ProcessingStep } from '../../../../ingestion/pipelines/steps'
import { EventHeaders } from '../../../../types'
import { EventIngestionRestrictionManager } from '../../../../utils/event-ingestion-restriction-manager'
import { SessionRecordingIngesterMetrics } from '../metrics'

type Input = { headers: EventHeaders }

export function createApplyOverflowRestrictionsStep<T extends Input>(
    restrictionManager: EventIngestionRestrictionManager,
    overflowTopic: string,
    consumeOverflow: boolean
): ProcessingStep<T, T> {
    return function applyOverflowRestrictionsStep(input: T): Promise<PipelineResult<T>> {
        const { headers } = input
        const { token, distinct_id } = headers

        // Skip overflow check if we're consuming from overflow topic
        if (consumeOverflow) {
            return Promise.resolve(ok(input))
        }

        // Check if this message should be forced to overflow
        if (restrictionManager.shouldForceOverflow(token, distinct_id)) {
            SessionRecordingIngesterMetrics.observeOverflowedByRestrictions(1)
            return Promise.resolve(redirect('overflow_forced', overflowTopic, false, false))
        }

        return Promise.resolve(ok(input))
    }
}

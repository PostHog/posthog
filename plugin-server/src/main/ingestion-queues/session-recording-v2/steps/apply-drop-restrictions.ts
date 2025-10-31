import { Message } from 'node-rdkafka'

import { PipelineResult, drop, ok } from '../../../../ingestion/pipelines/results'
import { ProcessingStep } from '../../../../ingestion/pipelines/steps'
import { EventHeaders } from '../../../../types'
import { EventIngestionRestrictionManager } from '../../../../utils/event-ingestion-restriction-manager'
import { SessionRecordingIngesterMetrics } from '../metrics'

type Input = { message: Message; headers: EventHeaders }
type Output = { message: Message; headers: EventHeaders }

export function createApplyDropRestrictionsStep(
    restrictionManager: EventIngestionRestrictionManager
): ProcessingStep<Input, Output> {
    return function applyDropRestrictionsStep(input: Input): Promise<PipelineResult<Output>> {
        const { headers } = input
        const { token, distinct_id } = headers

        // Check if this message should be dropped
        if (restrictionManager.shouldDropEvent(token, distinct_id)) {
            SessionRecordingIngesterMetrics.observeDroppedByRestrictions(1)
            return Promise.resolve(drop('blocked_token'))
        }

        return Promise.resolve(ok(input))
    }
}

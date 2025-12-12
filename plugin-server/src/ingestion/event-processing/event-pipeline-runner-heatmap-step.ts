import { DateTime } from 'luxon'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, PipelineEvent, PreIngestionEvent, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResult, isOkResult } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface EventPipelineRunnerHeatmapStepInput {
    normalizedEvent: PipelineEvent
    timestamp: DateTime
    team: Team
    headers: EventHeaders
    groupStoreForBatch: GroupStoreForBatch
}

export type EventPipelineRunnerHeatmapStepResult<TInput> = TInput & {
    preparedEvent: PreIngestionEvent
}

export function createEventPipelineRunnerHeatmapStep<TInput extends EventPipelineRunnerHeatmapStepInput>(
    config: {
        SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP: boolean
        TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE: number
        PIPELINE_STEP_STALLED_LOG_TIMEOUT: number
        PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: number
        PERSON_MERGE_ASYNC_ENABLED: boolean
        PERSON_MERGE_ASYNC_TOPIC: string
        PERSON_MERGE_SYNC_BATCH_SIZE: number
        PERSON_JSONB_SIZE_ESTIMATE_ENABLE: number
        PERSON_PROPERTIES_UPDATE_ALL: boolean
    },
    kafkaProducer: KafkaProducerWrapper,
    teamManager: TeamManager,
    groupTypeManager: GroupTypeManager,
    hogTransformer: HogTransformerService,
    personsStore: PersonsStore
): ProcessingStep<TInput, EventPipelineRunnerHeatmapStepResult<TInput>> {
    return async function eventPipelineRunnerHeatmapStep(
        input: TInput
    ): Promise<PipelineResult<EventPipelineRunnerHeatmapStepResult<TInput>>> {
        const { normalizedEvent, timestamp, team, headers, groupStoreForBatch } = input

        const runner = new EventPipelineRunner(
            config,
            kafkaProducer,
            teamManager,
            groupTypeManager,
            normalizedEvent,
            hogTransformer,
            personsStore,
            groupStoreForBatch,
            headers
        )
        const result = await runner.runHeatmapPipeline(normalizedEvent, timestamp, team)

        if (!isOkResult(result)) {
            return result
        }

        return {
            ...result,
            value: {
                ...input,
                preparedEvent: result.value.preparedEvent,
            },
        }
    }
}

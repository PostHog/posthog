import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, IncomingEventWithTeam } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { EventPipelineResult, EventPipelineRunner } from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { GroupStoreForBatch } from '../../worker/ingestion/groups/group-store-for-batch.interface'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResult, isOkResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface EventPipelineRunnerInput extends IncomingEventWithTeam {
    headers: EventHeaders
    groupStoreForBatch: GroupStoreForBatch
    processPerson: boolean
    forceDisablePersonProcessing: boolean
}

export type EventPipelineRunnerStepResult = EventPipelineResult & {
    inputHeaders: EventHeaders
    inputMessage: Message
}

export function createEventPipelineRunnerV1Step(
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
): ProcessingStep<EventPipelineRunnerInput, EventPipelineRunnerStepResult> {
    return async function eventPipelineRunnerV1Step(
        input: EventPipelineRunnerInput
    ): Promise<PipelineResult<EventPipelineRunnerStepResult>> {
        const {
            event,
            team,
            headers: inputHeaders,
            message: inputMessage,
            groupStoreForBatch,
            processPerson,
            forceDisablePersonProcessing,
        } = input

        const runner = new EventPipelineRunner(
            config,
            kafkaProducer,
            teamManager,
            groupTypeManager,
            event,
            hogTransformer,
            personsStore,
            groupStoreForBatch,
            inputHeaders
        )
        const result = await runner.runEventPipeline(event, team, processPerson, forceDisablePersonProcessing)

        if (isOkResult(result)) {
            const stepResult: EventPipelineRunnerStepResult = {
                ...result.value,
                inputHeaders,
                inputMessage,
            }
            return ok(stepResult, result.sideEffects, result.warnings)
        }

        return result
    }
}

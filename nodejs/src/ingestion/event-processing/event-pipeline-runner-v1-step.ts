import { Message } from 'node-rdkafka'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, IncomingEventWithTeam } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import {
    EventPipelineResult,
    EventPipelineRunner,
    EventPipelineRunnerOptions,
} from '../../worker/ingestion/event-pipeline/runner'
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
    config: EventPipelineRunnerOptions,
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

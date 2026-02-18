import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { EventHeaders, Person, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import {
    EventPipelineResult,
    EventPipelineRunner,
    EventPipelineRunnerOptions,
} from '../../worker/ingestion/event-pipeline/runner'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { PipelineResult, isOkResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface EventPipelineRunnerInput {
    message: Message
    eventWithPerson: PluginEvent
    timestamp: DateTime
    team: Team
    headers: EventHeaders
    processPerson: boolean
    person: Person
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
    groupStore: BatchWritingGroupStore
): ProcessingStep<EventPipelineRunnerInput, EventPipelineRunnerStepResult> {
    return async function eventPipelineRunnerV1Step(
        input: EventPipelineRunnerInput
    ): Promise<PipelineResult<EventPipelineRunnerStepResult>> {
        const {
            eventWithPerson,
            timestamp,
            team,
            headers: inputHeaders,
            message: inputMessage,
            processPerson,
            person,
        } = input

        const runner = new EventPipelineRunner(
            config,
            kafkaProducer,
            teamManager,
            groupTypeManager,
            eventWithPerson,
            groupStore,
            inputHeaders
        )
        const result = await runner.runEventPipeline(eventWithPerson, timestamp, team, processPerson, person)

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

import { PluginEvent } from '~/plugin-scaffold'

import { EventHeaders, PreIngestionEvent, Team } from '../../types'
import { TeamManager } from '../../utils/team-manager'
import { invalidTimestampCounter } from '../../worker/ingestion/event-pipeline/metrics'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { BatchWritingGroupStore } from '../../worker/ingestion/groups/batch-writing-group-store'
import { EventsProcessor } from '../../worker/ingestion/process-event'
import { parseEventTimestamp } from '../../worker/ingestion/timestamps'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { EventPipelineRunnerOptions } from './event-pipeline-options'

export type PrepareEventStepInput = {
    normalizedEvent: PluginEvent
    team: Team
    processPerson: boolean
    headers: EventHeaders
}

export type PrepareEventStepResult<TInput> = Omit<TInput, 'normalizedEvent'> & {
    preparedEvent: PreIngestionEvent
    historicalMigration: boolean
}

export function createPrepareEventStep<TInput extends PrepareEventStepInput>(
    teamManager: TeamManager,
    groupTypeManager: GroupTypeManager,
    groupStore: BatchWritingGroupStore,
    options: Pick<EventPipelineRunnerOptions, 'SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP'>
): ProcessingStep<TInput, PrepareEventStepResult<TInput>> {
    const eventsProcessor = new EventsProcessor(
        teamManager,
        groupTypeManager,
        options.SKIP_UPDATE_EVENT_AND_PROPERTIES_STEP
    )

    return async function prepareEventStep(input: TInput) {
        const { normalizedEvent, ...rest } = input

        const warnings: PipelineWarning[] = []
        const invalidTimestampCallback = function (type: string, details: Record<string, any>) {
            invalidTimestampCounter.labels(type).inc()
            warnings.push({ type, details })
        }

        const preparedEvent = await eventsProcessor.processEvent(
            String(normalizedEvent.distinct_id),
            normalizedEvent,
            input.team,
            parseEventTimestamp(normalizedEvent, invalidTimestampCallback),
            normalizedEvent.uuid,
            input.processPerson,
            groupStore
        )
        const historicalMigration = input.headers.historical_migration ?? false

        return ok(
            {
                ...rest,
                preparedEvent,
                historicalMigration,
            },
            [],
            warnings
        )
    }
}

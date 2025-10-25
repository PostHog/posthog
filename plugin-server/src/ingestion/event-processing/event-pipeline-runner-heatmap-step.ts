import { DateTime } from 'luxon'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { EventHeaders, Hub, PipelineEvent, PreIngestionEvent, Team } from '../../types'
import { EventPipelineHeatmapRunner } from '../../worker/ingestion/event-pipeline/runner'
import { PipelineResult, isOkResult } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface EventPipelineRunnerHeatmapStepInput {
    normalizedEvent: PipelineEvent
    timestamp: DateTime
    team: Team
    headers: EventHeaders
}

export type EventPipelineRunnerHeatmapStepResult<TInput> = TInput & {
    preparedEvent: PreIngestionEvent
}

export function createEventPipelineRunnerHeatmapStep<TInput extends EventPipelineRunnerHeatmapStepInput>(
    hub: Hub,
    hogTransformer: HogTransformerService
): ProcessingStep<TInput, EventPipelineRunnerHeatmapStepResult<TInput>> {
    return async function eventPipelineRunnerHeatmapStep(
        input: TInput
    ): Promise<PipelineResult<EventPipelineRunnerHeatmapStepResult<TInput>>> {
        const { normalizedEvent, timestamp, team, headers } = input

        const runner = new EventPipelineHeatmapRunner(hub, normalizedEvent, hogTransformer, headers)
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

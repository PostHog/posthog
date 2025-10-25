import { IncomingEvent, IncomingEventWithTeam } from '../../types'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface MapToPipelineEventStepInput {
    event: IncomingEvent
    eventWithTeam: IncomingEventWithTeam
}

/**
 * Maps the preprocessed event structure to the pipeline event structure.
 * Extracts the eventWithTeam which contains the PipelineEvent and flattens it.
 */
export function createMapToPipelineEventStep<T extends MapToPipelineEventStepInput>(): ProcessingStep<
    T,
    IncomingEventWithTeam
> {
    return function mapToPipelineEventStep(input: T): Promise<PipelineResult<IncomingEventWithTeam>> {
        return Promise.resolve(ok(input.eventWithTeam))
    }
}

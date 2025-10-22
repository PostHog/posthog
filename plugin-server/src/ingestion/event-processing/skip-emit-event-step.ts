import { PreIngestionEvent, RawKafkaEvent } from '../../types'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface SkipEmitEventStepInput {
    preparedEvent: PreIngestionEvent
}

export interface SkipEmitEventStepResult {
    eventToEmit?: RawKafkaEvent
}

export function createSkipEmitEventStep<TInput extends SkipEmitEventStepInput>(): ProcessingStep<
    TInput,
    SkipEmitEventStepResult
> {
    return function skipEmitEventStep(_input: TInput): Promise<PipelineResult<SkipEmitEventStepResult>> {
        return Promise.resolve(ok({ eventToEmit: undefined }))
    }
}

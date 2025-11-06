import { PipelineEvent } from '../../types'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createDropExceptionEventsStep<T extends { event: PipelineEvent }>(): ProcessingStep<T, T> {
    return async function dropExceptionEventsStep(input) {
        const { event } = input

        if (event.event === '$exception') {
            return Promise.resolve(drop('exception_event'))
        }

        return Promise.resolve(ok(input))
    }
}

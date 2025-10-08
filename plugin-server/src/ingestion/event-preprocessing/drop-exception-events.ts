import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { IncomingEvent } from '../../types'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createDropExceptionEventsStep<T extends { event: IncomingEvent }>(): ProcessingStep<T, T> {
    return async function dropExceptionEventsStep(input) {
        const { event } = input

        if (event.event.event === '$exception') {
            eventDroppedCounter
                .labels({
                    event_type: 'analytics',
                    drop_cause: 'exception_event',
                })
                .inc()
            return Promise.resolve(drop('Exception events are processed separately in Rust'))
        }

        return Promise.resolve(ok(input))
    }
}

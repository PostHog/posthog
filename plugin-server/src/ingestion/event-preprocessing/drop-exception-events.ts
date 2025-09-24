import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { IncomingEvent } from '../../types'
import { drop, ok } from '../pipelines/results'
import { SyncProcessingStep } from '../pipelines/steps'

export function createDropExceptionEventsStep<T extends { event: IncomingEvent }>(): SyncProcessingStep<T, T> {
    return function dropExceptionEventsStep(input) {
        const { event } = input

        if (event.event.event === '$exception') {
            eventDroppedCounter
                .labels({
                    event_type: 'analytics',
                    drop_cause: 'exception_event',
                })
                .inc()
            return drop('Exception events are processed separately in Rust')
        }

        return ok(input)
    }
}

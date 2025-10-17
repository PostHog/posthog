import { eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import { IncomingEventWithTeam } from '../../types'
import { UUID } from '../../utils/utils'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

function validateEventUuid(eventWithTeam: IncomingEventWithTeam): {
    valid: boolean
    warning?: PipelineWarning
    dropCause?: string
} {
    const { event } = eventWithTeam

    if (!event.uuid) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'empty_uuid',
            })
            .inc()
        return {
            valid: false,
            warning: {
                type: 'skipping_event_invalid_uuid',
                details: {
                    eventUuid: JSON.stringify(event.uuid),
                },
            },
            dropCause: 'empty_uuid',
        }
    }

    if (!UUID.validateString(event.uuid, false)) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'invalid_uuid',
            })
            .inc()
        return {
            valid: false,
            warning: {
                type: 'skipping_event_invalid_uuid',
                details: {
                    eventUuid: JSON.stringify(event.uuid),
                },
            },
            dropCause: 'invalid_uuid',
        }
    }

    return { valid: true }
}

export function createValidateEventUuidStep<T extends { eventWithTeam: IncomingEventWithTeam }>(): ProcessingStep<
    T,
    T
> {
    return async function validateEventUuidStep(input) {
        const { eventWithTeam } = input
        const validation = validateEventUuid(eventWithTeam)
        if (!validation.valid) {
            return drop(validation.dropCause || 'invalid_uuid', [], validation.warning ? [validation.warning] : [])
        }
        return Promise.resolve(ok(input))
    }
}

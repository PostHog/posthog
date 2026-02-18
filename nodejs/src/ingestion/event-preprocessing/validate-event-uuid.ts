import { PipelineEvent } from '../../types'
import { UUID } from '../../utils/utils'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

type ValidateEventUuidError = { error: true; cause: 'empty_uuid' | 'invalid_uuid'; warning: PipelineWarning }
type ValidateEventUuidSuccess = { error: false }
type ValidateEventUuidResult = ValidateEventUuidSuccess | ValidateEventUuidError

function validateEventUuid(event: PipelineEvent): ValidateEventUuidResult {
    if (!event.uuid) {
        return {
            error: true,
            cause: 'empty_uuid',
            warning: {
                type: 'skipping_event_invalid_uuid',
                details: {
                    eventUuid: JSON.stringify(event.uuid),
                },
            },
        }
    }

    if (!UUID.validateString(event.uuid, false)) {
        return {
            error: true,
            cause: 'invalid_uuid',
            warning: {
                type: 'skipping_event_invalid_uuid',
                details: {
                    eventUuid: JSON.stringify(event.uuid),
                },
            },
        }
    }

    return { error: false }
}

export function createValidateEventUuidStep<T extends { event: PipelineEvent }>(): ProcessingStep<T, T> {
    return async function validateEventUuidStep(input) {
        const { event } = input
        const result = validateEventUuid(event)
        if (result.error) {
            return drop(result.cause, [], [result.warning])
        }
        return Promise.resolve(ok(input))
    }
}

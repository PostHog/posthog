import { EventHeaders } from '../../types'
import { PipelineWarning } from '../pipelines/pipeline.interface'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

const MAX_DISTINCT_ID_LENGTH = 400

type ValidateEventMetadataError = {
    error: true
    cause: 'distinct_id_too_long'
    warning: PipelineWarning
}
type ValidateEventMetadataSuccess = { error: false }
type ValidateEventMetadataResult = ValidateEventMetadataSuccess | ValidateEventMetadataError

function validateEventMetadata(headers: EventHeaders): ValidateEventMetadataResult {
    const { distinct_id } = headers

    if (distinct_id && distinct_id.length > MAX_DISTINCT_ID_LENGTH) {
        return {
            error: true,
            cause: 'distinct_id_too_long',
            warning: {
                type: 'skipping_event_invalid_distinct_id',
                details: {
                    distinctId: distinct_id.substring(0, 100),
                    distinctIdLength: distinct_id.length,
                    maxLength: MAX_DISTINCT_ID_LENGTH,
                },
            },
        }
    }

    return { error: false }
}

export function createValidateEventMetadataStep<T extends { headers: EventHeaders }>(): ProcessingStep<T, T> {
    return async function validateEventMetadataStep(input) {
        const { headers } = input
        const result = validateEventMetadata(headers)
        if (result.error) {
            return drop(result.cause, [], [result.warning])
        }
        return Promise.resolve(ok(input))
    }
}

import { PipelineEvent } from '../../types'
import { drop, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export function createValidateEventPropertiesStep<T extends { event: PipelineEvent }>(): ProcessingStep<T, T> {
    return async function validateEventPropertiesStep(input) {
        const { event } = input

        // Validate $groupidentify group_key length
        if (event.event === '$groupidentify') {
            const groupKey = event.properties?.$group_key
            if (groupKey && groupKey.toString().length > 400) {
                return drop(
                    'group_key_too_long',
                    [],
                    [
                        {
                            type: 'group_key_too_long',
                            details: {
                                eventUuid: event.uuid,
                                event: event.event,
                                distinctId: event.distinct_id,
                                groupKey,
                                groupKeyLength: groupKey.toString().length,
                                maxLength: 400,
                            },
                        },
                    ]
                )
            }
        }

        return Promise.resolve(ok(input))
    }
}

import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PipelineEvent } from '~/types'

// posthog_group.group_key and posthog_grouptypemapping.group_type are both varchar(400).
const MAX_GROUP_IDENTIFIER_LENGTH = 400

// The pg driver sends an object parameter as JSON text, so measure what Postgres
// receives; `.toString()` would flatten an object to "[object Object]".
function postgresTextLength(value: unknown): number {
    return typeof value === 'object' ? JSON.stringify(value).length : String(value).length
}

export function createValidateEventPropertiesStep<T extends { event: PipelineEvent }>(): ProcessingStep<T, T> {
    return async function validateEventPropertiesStep(input) {
        const { event } = input

        if (event.event === '$groupidentify') {
            const groupKey = event.properties?.$group_key
            if (groupKey && groupKey.toString().length > MAX_GROUP_IDENTIFIER_LENGTH) {
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
                                maxLength: MAX_GROUP_IDENTIFIER_LENGTH,
                            },
                        },
                    ]
                )
            }

            const groupType = event.properties?.$group_type
            const groupTypeLength = groupType ? postgresTextLength(groupType) : 0
            if (groupTypeLength > MAX_GROUP_IDENTIFIER_LENGTH) {
                return drop(
                    'group_type_too_long',
                    [],
                    [
                        {
                            type: 'group_type_too_long',
                            details: {
                                eventUuid: event.uuid,
                                event: event.event,
                                distinctId: event.distinct_id,
                                groupKey,
                                groupType: String(groupType).substring(0, 100),
                                groupTypeLength,
                                maxLength: MAX_GROUP_IDENTIFIER_LENGTH,
                            },
                        },
                    ]
                )
            }
        }

        return Promise.resolve(ok(input))
    }
}

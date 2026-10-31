import { MAX_GROUP_TYPE_LENGTH } from '~/common/groups/group-type-manager'
import { asPostgresParameterText } from '~/common/utils/db/utils'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PipelineEvent } from '~/types'

// posthog_group.group_key is varchar(400).
const MAX_GROUP_KEY_LENGTH = 400

export function createValidateEventPropertiesStep<T extends { event: PipelineEvent }>(): ProcessingStep<T, T> {
    return async function validateEventPropertiesStep(input) {
        const { event } = input

        if (event.event === '$groupidentify') {
            const groupKey = event.properties?.$group_key
            const groupKeyText = groupKey ? asPostgresParameterText(groupKey) : ''
            if (groupKeyText.length > MAX_GROUP_KEY_LENGTH) {
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
                                groupKeyLength: groupKeyText.length,
                                maxLength: MAX_GROUP_KEY_LENGTH,
                            },
                        },
                    ]
                )
            }

            const groupType = event.properties?.$group_type
            const groupTypeText = groupType ? asPostgresParameterText(groupType) : ''
            if (groupTypeText.length > MAX_GROUP_TYPE_LENGTH) {
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
                                groupType: groupTypeText.substring(0, 100),
                                groupTypeLength: groupTypeText.length,
                                maxLength: MAX_GROUP_TYPE_LENGTH,
                            },
                        },
                    ]
                )
            }
        }

        return Promise.resolve(ok(input))
    }
}

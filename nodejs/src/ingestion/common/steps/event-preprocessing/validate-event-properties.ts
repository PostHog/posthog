import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PipelineEvent } from '~/types'

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

        // $anon_distinct_id and alias name the other side of a person merge and reach String() in
        // PersonMergeService, which throws for a non-string like { toString: null } — an unhandled
        // rejection that crashes the consumer and, with the offset uncommitted, wedges the partition when
        // Kafka redelivers the event. A non-string can't identify a person anyway; distinct IDs are strings.
        if (
            event.event === '$identify' ||
            event.event === '$create_alias' ||
            event.event === '$merge_dangerously'
        ) {
            const properties = event.properties ?? {}

            for (const [property, warningType] of [
                ['$anon_distinct_id', 'invalid_anon_distinct_id'],
                ['alias', 'invalid_alias'],
            ] as const) {
                const value = properties[property]
                if (value != null && typeof value !== 'string') {
                    return drop(
                        warningType,
                        [],
                        [
                            {
                                type: warningType,
                                details: {
                                    eventUuid: event.uuid,
                                    event: event.event,
                                    distinctId: event.distinct_id,
                                    receivedType: Array.isArray(value) ? 'array' : typeof value,
                                },
                            },
                        ]
                    )
                }
            }
        }

        return Promise.resolve(ok(input))
    }
}

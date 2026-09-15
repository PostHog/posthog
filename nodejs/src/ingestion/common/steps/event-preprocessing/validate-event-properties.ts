import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PipelineEvent } from '~/types'

const MAX_GROUP_KEY_LENGTH = 400

// $group_key / $group_type on a $groupidentify are caller-controlled JSON. A present-but-non-string
// value (an object like `{ "toString": null }`, an array, a number, ...) can't identify a group, and
// worse: the group write path coerces it with `String()` / `.toString()`, which THROWS for a poisoned
// value. That throw surfaces as an unhandled rejection that crashes the ingestion consumer and — because
// the offset is never committed — blocks the partition on the same event when Kafka redelivers it (a
// poison pill affecting every team on the partition). Reject such events up front with a warning, the
// same way $group_set is guarded (#72866).
export function createValidateEventPropertiesStep<T extends { event: PipelineEvent }>(): ProcessingStep<T, T> {
    return async function validateEventPropertiesStep(input) {
        const { event } = input

        if (event.event === '$groupidentify') {
            const properties = event.properties ?? {}

            for (const [property, warningType] of [
                ['$group_key', 'invalid_group_key'],
                ['$group_type', 'invalid_group_type'],
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

            // Safe now: a non-string $group_key was rejected above, so `.length` can't throw.
            const groupKey = properties.$group_key
            if (typeof groupKey === 'string' && groupKey.length > MAX_GROUP_KEY_LENGTH) {
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
                                groupKeyLength: groupKey.length,
                                maxLength: MAX_GROUP_KEY_LENGTH,
                            },
                        },
                    ]
                )
            }
        }

        return ok(input)
    }
}

/* This file contains the logic to report custom frontend events */
import { kea } from 'kea'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'
import { eventUsageLogicType } from 'types/lib/utils/eventUsageLogicType'
import { AnnotationType } from '~/types'

const keyMappingKeys = Object.keys(keyMapping.event)

export const eventUsageLogic = kea<eventUsageLogicType>({
    actions: {
        reportAnnotationViewed: (annotations) => ({ annotations }),
        reportPersonDetailViewed: (person) => ({ person }),
    },
    listeners: {
        reportAnnotationViewed: async ({ annotations }: { annotations: AnnotationType[] | null }, breakpoint) => {
            if (!annotations) {
                // If value is `null` the component has been unmounted, don't report
                return
            }

            await breakpoint(500) // Debounce calls to make sure we don't report accidentally hovering over an annotation.

            for (const annotation of annotations) {
                /* Report one event per annotation */
                const properties = {
                    total_items_count: annotations.length,
                    content_length: annotation.content.length,
                    scope: annotation.scope,
                    deleted: annotation.deleted,
                    created_by_me: annotation.created_by && annotation.created_by?.id === userLogic.values.user?.id,
                    creation_type: annotation.creation_type,
                    created_at: annotation.created_at,
                    updated_at: annotation.updated_at,
                }
                posthog.capture('annotation viewed', properties)
            }
        },
        reportPersonDetailViewed: async ({ person }, breakpoint) => {
            await breakpoint(500)

            let custom_properties_count = 0
            let posthog_properties_count = 0
            for (const prop of Object.keys(person.properties)) {
                if (keyMappingKeys.includes(prop)) {
                    posthog_properties_count += 1
                } else {
                    custom_properties_count += 1
                }
            }

            const properties = {
                properties_count: Object.keys(person.properties).length,
                is_identified: person.is_identified,
                has_email: !!person.properties.email,
                has_name: !!person.properties.name,
                custom_properties_count,
                posthog_properties_count,
            }
            posthog.capture('person viewed', properties)
        },
    },
})

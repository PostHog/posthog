import { kea } from 'kea'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'
import { eventUsageLogicType } from 'types/lib/utils/eventUsageLogicType'
import { AnnotationType } from '~/types'

export const eventUsageLogic = kea<eventUsageLogicType>({
    actions: {
        reportAnnotationViewed: (payload) => ({ payload }),
    },
    listeners: {
        reportAnnotationViewed: async ({ payload }: { payload: AnnotationType[] | null }, breakpoint) => {
            if (!payload) {
                // If value is `null` the component has been unmounted, we cancel the report if the timeout hasn't elapsed
                return
            }
            await breakpoint(1500)

            for (const annotation of payload) {
                /* Report one event per annotation */
                const properties = {
                    total_items_count: payload.length,
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
    },
})

import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import type { promotedEventPropertiesModelType } from './promotedEventPropertiesModelType'

export const promotedEventPropertiesModel = kea<promotedEventPropertiesModelType>([
    path(['models', 'promotedEventPropertiesModel']),
    loaders(() => ({
        promotedProperties: {
            __default: {} as Record<string, string>,
            loadPromotedProperties: async () => {
                const response = await api.eventDefinitions.promotedProperties()
                return response.promoted_properties || {}
            },
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPromotedProperties()
    }),
])

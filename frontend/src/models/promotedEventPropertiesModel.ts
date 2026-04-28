import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { hasTaxonomyPromotedProperty } from 'lib/utils/promotedEventProperty'

import type { promotedEventPropertiesModelType } from './promotedEventPropertiesModelType'

export const promotedEventPropertiesModel = kea<promotedEventPropertiesModelType>([
    path(['models', 'promotedEventPropertiesModel']),
    actions({
        ensureLoadedForEvents: (eventNames: string[]) => ({ eventNames }),
        refreshLoadedPromotedProperties: true,
    }),
    loaders(({ values }) => ({
        promotedProperties: {
            __default: {} as Record<string, string>,
            loadPromotedProperties: async ({ names }: { names: string[] }) => {
                if (names.length === 0) {
                    return values.promotedProperties
                }
                const response = await api.eventDefinitions.promotedProperties({ names })
                const next = { ...values.promotedProperties }
                for (const name of names) {
                    delete next[name]
                }
                return { ...next, ...response.promoted_properties }
            },
        },
    })),
    reducers({
        loadedEventNames: [
            [] as string[],
            {
                loadPromotedProperties: (state, { names }) => Array.from(new Set([...state, ...names])),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        ensureLoadedForEvents: ({ eventNames }) => {
            const loaded = new Set(values.loadedEventNames)
            const namesToLoad = eventNames.filter(
                (name) => !!name && !hasTaxonomyPromotedProperty(name) && !loaded.has(name)
            )
            if (namesToLoad.length > 0) {
                actions.loadPromotedProperties({ names: namesToLoad })
            }
        },
        refreshLoadedPromotedProperties: () => {
            if (values.loadedEventNames.length > 0) {
                actions.loadPromotedProperties({ names: values.loadedEventNames })
            }
        },
    })),
])

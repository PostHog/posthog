import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { hasTaxonomyPrimaryProperty } from 'lib/utils/primaryEventProperty'

import type { primaryEventPropertiesModelType } from './primaryEventPropertiesModelType'

export const primaryEventPropertiesModel = kea<primaryEventPropertiesModelType>([
    path(['models', 'primaryEventPropertiesModel']),
    actions({
        ensureLoadedForEvents: (eventNames: string[]) => ({ eventNames }),
        refreshLoadedPrimaryProperties: true,
    }),
    loaders(({ values }) => ({
        primaryProperties: {
            __default: {} as Record<string, string>,
            loadPrimaryProperties: async ({ names }: { names: string[] }) => {
                if (names.length === 0) {
                    return values.primaryProperties
                }
                const response = await api.eventDefinitions.primaryProperties({ names })
                const next = { ...values.primaryProperties }
                for (const name of names) {
                    delete next[name]
                }
                return { ...next, ...response.primary_properties }
            },
        },
    })),
    reducers({
        loadedEventNames: [
            [] as string[],
            {
                loadPrimaryProperties: (state, { names }) => Array.from(new Set([...state, ...names])),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        ensureLoadedForEvents: ({ eventNames }) => {
            const loaded = new Set(values.loadedEventNames)
            const namesToLoad = eventNames.filter(
                (name) => !!name && !hasTaxonomyPrimaryProperty(name) && !loaded.has(name)
            )
            if (namesToLoad.length > 0) {
                actions.loadPrimaryProperties({ names: namesToLoad })
            }
        },
        refreshLoadedPrimaryProperties: () => {
            if (values.loadedEventNames.length > 0) {
                actions.loadPrimaryProperties({ names: values.loadedEventNames })
            }
        },
    })),
])

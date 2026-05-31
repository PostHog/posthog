import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { hasTaxonomyPrimaryProperty } from 'lib/utils/primaryEventProperty'

import type { primaryEventPropertiesModelType } from './primaryEventPropertiesModelType'

export const primaryEventPropertiesModel = kea<primaryEventPropertiesModelType>([
    path(['models', 'primaryEventPropertiesModel']),
    actions({
        ensureLoadedForEvents: (eventNames: string[]) => ({ eventNames }),
        refreshLoadedPrimaryProperties: true,
        setPrimaryProperty: (eventName: string, propertyKey: string | null) => ({ eventName, propertyKey }),
        applyOptimisticPrimaryProperty: (eventName: string, propertyKey: string | null) => ({
            eventName,
            propertyKey,
        }),
        finishSavingPrimaryProperty: (eventName: string) => ({ eventName }),
    }),
    loaders(({ values }) => ({
        loadedPrimaryProperties: {
            __default: {} as Record<string, string>,
            loadPrimaryProperties: async ({ names }: { names: string[] }) => {
                if (names.length === 0) {
                    return values.loadedPrimaryProperties
                }
                const response = await api.eventDefinitions.primaryProperties({ names })
                const next = { ...values.loadedPrimaryProperties }
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
        optimisticPrimaryProperties: [
            {} as Record<string, string | null>,
            {
                applyOptimisticPrimaryProperty: (state, { eventName, propertyKey }) => ({
                    ...state,
                    [eventName]: propertyKey,
                }),
            },
        ],
        savingPrimaryPropertyForEvents: [
            [] as string[],
            {
                setPrimaryProperty: (state, { eventName }) => Array.from(new Set([...state, eventName])),
                finishSavingPrimaryProperty: (state, { eventName }) => state.filter((name) => name !== eventName),
            },
        ],
    }),
    selectors({
        primaryProperties: [
            (s) => [s.loadedPrimaryProperties, s.optimisticPrimaryProperties],
            (loaded, optimistic): Record<string, string> => {
                const merged = { ...loaded }
                for (const [eventName, propertyKey] of Object.entries(optimistic)) {
                    if (propertyKey) {
                        merged[eventName] = propertyKey
                    } else {
                        delete merged[eventName]
                    }
                }
                return merged
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
        setPrimaryProperty: async ({ eventName, propertyKey }) => {
            const previous = values.primaryProperties[eventName] ?? null
            actions.applyOptimisticPrimaryProperty(eventName, propertyKey)
            try {
                const definition = await api.eventDefinitions.byName({ name: eventName })
                await api.eventDefinitions.update({
                    eventDefinitionId: definition.id,
                    eventDefinitionData: { primary_property: propertyKey },
                })
            } catch {
                actions.applyOptimisticPrimaryProperty(eventName, previous)
                lemonToast.error('Could not update the pinned property. Please try again.')
            } finally {
                actions.finishSavingPrimaryProperty(eventName)
            }
        },
    })),
])

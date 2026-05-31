import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { hasTaxonomyPrimaryProperty } from 'lib/utils/primaryEventProperty'

import type { primaryEventPropertiesModelType } from './primaryEventPropertiesModelType'

export const primaryEventPropertiesModel = kea<primaryEventPropertiesModelType>([
    path(['models', 'primaryEventPropertiesModel']),
    actions({
        ensureLoadedForEvents: (eventNames: string[]) => ({ eventNames }),
        refreshLoadedPrimaryProperties: true,
        loadPrimaryProperties: (names: string[]) => ({ names }),
        primaryPropertiesLoaded: (names: string[], primaryProperties: Record<string, string>) => ({
            names,
            primaryProperties,
        }),
        setPrimaryProperty: (eventName: string, propertyKey: string | null) => ({ eventName, propertyKey }),
        applyOptimisticPrimaryProperty: (eventName: string, propertyKey: string | null) => ({
            eventName,
            propertyKey,
        }),
        clearOptimisticPrimaryProperty: (eventName: string) => ({ eventName }),
        setLoadedPrimaryProperty: (eventName: string, propertyKey: string | null) => ({ eventName, propertyKey }),
        finishSavingPrimaryProperty: (eventName: string) => ({ eventName }),
    }),
    reducers({
        loadedPrimaryProperties: [
            {} as Record<string, string>,
            {
                primaryPropertiesLoaded: (state, { names, primaryProperties }) => {
                    const next = { ...state }
                    for (const name of names) {
                        delete next[name]
                    }
                    return { ...next, ...primaryProperties }
                },
                setLoadedPrimaryProperty: (state, { eventName, propertyKey }) => {
                    if (propertyKey) {
                        return { ...state, [eventName]: propertyKey }
                    }
                    const next = { ...state }
                    delete next[eventName]
                    return next
                },
            },
        ],
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
                clearOptimisticPrimaryProperty: (state, { eventName }) => {
                    const next = { ...state }
                    delete next[eventName]
                    return next
                },
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
                actions.loadPrimaryProperties(namesToLoad)
            }
        },
        refreshLoadedPrimaryProperties: () => {
            if (values.loadedEventNames.length > 0) {
                actions.loadPrimaryProperties(values.loadedEventNames)
            }
        },
        loadPrimaryProperties: async ({ names }) => {
            if (names.length === 0) {
                return
            }
            const response = await api.eventDefinitions.primaryProperties({ names })
            actions.primaryPropertiesLoaded(names, response.primary_properties)
        },
        setPrimaryProperty: async ({ eventName, propertyKey }) => {
            actions.applyOptimisticPrimaryProperty(eventName, propertyKey)
            try {
                const definition = await api.eventDefinitions.byName({ name: eventName })
                await api.eventDefinitions.update({
                    eventDefinitionId: definition.id,
                    eventDefinitionData: { primary_property: propertyKey },
                })
                actions.setLoadedPrimaryProperty(eventName, propertyKey)
            } catch {
                lemonToast.error('Could not update the pinned property. Please try again.')
            } finally {
                actions.clearOptimisticPrimaryProperty(eventName)
                actions.finishSavingPrimaryProperty(eventName)
            }
        },
    })),
])

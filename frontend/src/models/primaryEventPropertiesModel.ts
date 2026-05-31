import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

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
                primaryPropertiesLoaded: (state, { names }) => Array.from(new Set([...state, ...names])),
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
        primaryPropertySaveVersions: [
            {} as Record<string, number>,
            {
                setLoadedPrimaryProperty: (state, { eventName }) => ({
                    ...state,
                    [eventName]: (state[eventName] ?? 0) + 1,
                }),
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
            const versionsAtRequest = values.primaryPropertySaveVersions
            try {
                const response = await api.eventDefinitions.primaryProperties({ names })
                const supersededBySave = (name: string): boolean =>
                    (values.primaryPropertySaveVersions[name] ?? 0) !== (versionsAtRequest[name] ?? 0)
                const namesToApply = names.filter((name) => !supersededBySave(name))
                if (namesToApply.length === 0) {
                    return
                }
                const propertiesToApply = Object.fromEntries(
                    Object.entries(response.primary_properties).filter(([name]) => !supersededBySave(name))
                )
                actions.primaryPropertiesLoaded(namesToApply, propertiesToApply)
            } catch (error) {
                posthog.captureException(error, { action: 'load-primary-properties' })
            }
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
            } catch (error) {
                posthog.captureException(error, { action: 'set-primary-property' })
                lemonToast.error('Could not update the pinned property. Please try again.')
            } finally {
                actions.clearOptimisticPrimaryProperty(eventName)
                actions.finishSavingPrimaryProperty(eventName)
            }
        },
    })),
])

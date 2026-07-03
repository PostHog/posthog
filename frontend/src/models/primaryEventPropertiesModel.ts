import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { hasTaxonomyPrimaryProperty } from 'lib/utils/events'

import type { primaryEventPropertiesModelType } from './primaryEventPropertiesModelType'

export const primaryEventPropertiesModel = kea<primaryEventPropertiesModelType>([
    path(['models', 'primaryEventPropertiesModel']),
    actions({
        ensureLoadedForEvents: (eventNames: string[]) => ({ eventNames }),
        refreshLoadedPrimaryProperties: true,
        markPrimaryPropertiesLoaded: (names: string[]) => ({ names }),
    }),
    loaders(({ values, actions }) => ({
        primaryProperties: {
            __default: {} as Record<string, string>,
            loadPrimaryProperties: async ({ names }: { names: string[] }) => {
                if (names.length === 0) {
                    return values.primaryProperties
                }
                try {
                    const response = await api.eventDefinitions.primaryProperties({ names })
                    const next = { ...values.primaryProperties }
                    for (const name of names) {
                        delete next[name]
                    }
                    // Only mark names as loaded once the fetch succeeds, so a failed lookup
                    // stays retryable on the next ensureLoadedForEvents call.
                    actions.markPrimaryPropertiesLoaded(names)
                    return { ...next, ...response.primary_properties }
                } catch (error) {
                    // This is a non-critical auxiliary lookup: consumers fall back to core taxonomy
                    // defaults when an override is missing, so we swallow the error rather than let it
                    // reach the global kea-loaders toast. Report it and leave the names untracked so
                    // they can be retried later.
                    posthog.captureException(error, { action: 'load-primary-properties' })
                    return values.primaryProperties
                }
            },
            updatePrimaryProperty: async ({
                eventName,
                propertyKey,
            }: {
                eventName: string
                propertyKey: string | null
            }) => {
                let definitionId: string
                try {
                    definitionId = (await api.eventDefinitions.byName({ name: eventName })).id
                } catch (error) {
                    posthog.captureException(error, { action: 'update-primary-property', stage: 'lookup' })
                    lemonToast.error(`We couldn't find a definition for "${eventName}" yet. Please try again shortly.`)
                    return values.primaryProperties
                }
                try {
                    const updated = await api.eventDefinitions.update({
                        eventDefinitionId: definitionId,
                        eventDefinitionData: { primary_property: propertyKey },
                    })
                    const next = { ...values.primaryProperties }
                    if (updated.primary_property) {
                        next[eventName] = updated.primary_property
                    } else {
                        delete next[eventName]
                    }
                    return next
                } catch (error) {
                    posthog.captureException(error, { action: 'update-primary-property', stage: 'update' })
                    lemonToast.error('Could not update the pinned property. Please try again.')
                    return values.primaryProperties
                }
            },
        },
    })),
    reducers({
        loadedEventNames: [
            [] as string[],
            {
                markPrimaryPropertiesLoaded: (state, { names }) => Array.from(new Set([...state, ...(names ?? [])])),
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

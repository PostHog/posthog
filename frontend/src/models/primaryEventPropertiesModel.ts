import { actions, isBreakpoint, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
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
    }),
    loaders(({ values }) => ({
        primaryProperties: {
            __default: {} as Record<string, string>,
            loadPrimaryProperties: async ({ names }: { names: string[] }, breakpoint) => {
                if (names.length === 0) {
                    return values.primaryProperties
                }
                const response = await api.eventDefinitions.primaryProperties({ names })
                // Bail out if the logic unmounted mid-request, otherwise the post-await
                // selector read below can no longer resolve and throws "[KEA] Can not find path".
                breakpoint()
                const next = { ...values.primaryProperties }
                for (const name of names) {
                    delete next[name]
                }
                return { ...next, ...response.primary_properties }
            },
            updatePrimaryProperty: async (
                {
                    eventName,
                    propertyKey,
                }: {
                    eventName: string
                    propertyKey: string | null
                },
                breakpoint
            ) => {
                // Snapshot before any await so the error paths don't re-read a selector
                // that may no longer be resolvable if the logic has since unmounted.
                const currentProperties = values.primaryProperties
                let definitionId: string
                try {
                    definitionId = (await api.eventDefinitions.byName({ name: eventName })).id
                } catch (error) {
                    posthog.captureException(error, { action: 'update-primary-property', stage: 'lookup' })
                    lemonToast.error(`We couldn't find a definition for "${eventName}" yet. Please try again shortly.`)
                    return currentProperties
                }
                breakpoint()
                try {
                    const updated = await api.eventDefinitions.update({
                        eventDefinitionId: definitionId,
                        eventDefinitionData: { primary_property: propertyKey },
                    })
                    breakpoint()
                    const next = { ...values.primaryProperties }
                    if (updated.primary_property) {
                        next[eventName] = updated.primary_property
                    } else {
                        delete next[eventName]
                    }
                    return next
                } catch (error: any) {
                    // Let kea swallow the unmount cancellation instead of reporting it as a failure.
                    if (isBreakpoint(error)) {
                        throw error
                    }
                    posthog.captureException(error, { action: 'update-primary-property', stage: 'update' })
                    lemonToast.error('Could not update the pinned property. Please try again.')
                    return currentProperties
                }
            },
        },
    })),
    reducers({
        loadedEventNames: [
            [] as string[],
            {
                loadPrimaryPropertiesSuccess: (state, { payload }) =>
                    Array.from(new Set([...state, ...(payload?.names ?? [])])),
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
        loadPrimaryPropertiesFailure: ({ errorObject }) => {
            posthog.captureException(errorObject, { action: 'load-primary-properties' })
        },
    })),
])

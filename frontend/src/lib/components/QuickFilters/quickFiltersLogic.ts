import { actions, afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter } from '~/types'

import { QuickFiltersEvents } from './consts'
import type { quickFiltersLogicType } from './quickFiltersLogicType'

export interface QuickFiltersLogicProps {
    context: QuickFilterContext
}

export const quickFiltersLogic = kea<quickFiltersLogicType>([
    path(['lib', 'components', 'QuickFilters', 'quickFiltersLogic']),
    props({} as QuickFiltersLogicProps),
    key((props) => props.context),

    actions({
        createFilter: (payload: Pick<QuickFilter, 'name' | 'property_name' | 'type' | 'options'>) => ({
            payload,
        }),
        updateFilter: (
            id: string,
            payload: Partial<Pick<QuickFilter, 'name' | 'property_name' | 'type' | 'options'>>
        ) => ({ id, payload }),
        deleteFilter: (id: string) => ({ id }),
        filterUpdated: (filter: QuickFilter) => ({ filter }),
    }),

    loaders(({ values, props, actions }) => ({
        quickFilters: [
            [] as QuickFilter[],
            {
                loadQuickFilters: async () => {
                    const response = await api.quickFilters.list(props.context)
                    return response.results
                },
                createFilter: async ({ payload }) => {
                    const newFilter = await api.quickFilters.create({
                        ...payload,
                        contexts: [props.context],
                    })

                    lemonToast.success('Quick filter created successfully')
                    posthog.capture(QuickFiltersEvents.QuickFilterCreated, {
                        name: payload.name,
                        property_name: payload.property_name,
                        type: payload.type,
                        options: payload.options,
                        context: props.context,
                    })
                    return [newFilter, ...values.quickFilters]
                },
                updateFilter: async ({ id, payload }) => {
                    const updatedFilter = await api.quickFilters.update(id, payload)
                    lemonToast.success('Quick filter updated successfully')
                    posthog.capture(QuickFiltersEvents.QuickFilterUpdated, {
                        ...(payload.name && { name: payload.name }),
                        ...(payload.property_name && { property_name: payload.property_name }),
                        ...(payload.type && { type: payload.type }),
                        ...(payload.options && { options: payload.options }),
                        context: props.context,
                    })
                    actions.filterUpdated(updatedFilter)
                    return values.quickFilters.map((f: QuickFilter) => (f.id === id ? updatedFilter : f))
                },
                deleteFilter: async ({ id }) => {
                    await api.quickFilters.delete(id)
                    lemonToast.success('Quick filter deleted successfully')
                    return values.quickFilters.filter((f: QuickFilter) => f.id !== id)
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadQuickFilters()
    }),
])

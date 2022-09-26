import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import api, { PaginatedResponse } from 'lib/api'
import type { exploreLogicType } from './exploreLogicType'
import { AnyPropertyFilter, ExploreCategory } from '~/types'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

export const categories: Record<ExploreCategory, any> = {
    [ExploreCategory.Events]: 'Events',
    [ExploreCategory.People]: 'People',
    [ExploreCategory.Recordings]: 'Recordings',
}

export const categorySelectOptions = Object.entries(categories).map(([value, label]) => ({ value, label }))

export const endpoints: Record<
    ExploreCategory,
    (filters: AnyPropertyFilter[] | null) => Promise<PaginatedResponse<any>>
> = {
    [ExploreCategory.Events]: (filters) => api.events.list({ properties: filters ?? [] }),
    [ExploreCategory.People]: (filters) => api.persons.list({ properties: filters ?? [] }),
    [ExploreCategory.Recordings]: () => api.sessionRecordings.list(),
}

export const exploreLogic = kea<exploreLogicType>([
    path(['scenes', 'explore', 'exploreLogic']),
    actions({
        setCategory: (category: ExploreCategory) => ({ category }),
        setFilters: (filters: AnyPropertyFilter[] | null) => ({ filters }),
        reloadData: true,
    }),
    reducers({
        category: [ExploreCategory.Events as ExploreCategory, { setCategory: (_, { category }) => category }],
        filters: [null as AnyPropertyFilter[] | null, { setFilters: (_, { filters }) => filters }],
    }),
    listeners(({ actions }) => ({
        setCategory: () => actions.reloadData(),
        setFilters: () => actions.reloadData(),
    })),
    loaders(({ values }) => ({
        rawData: [
            { results: [] } as PaginatedResponse<any>,
            {
                reloadData: async (_, breakpoint) => {
                    await breakpoint(1)
                    const { category, filters } = values
                    const results = await endpoints[category](filters)
                    breakpoint()
                    return results
                },
            },
        ],
    })),
    selectors({
        rows: [(s) => [s.rawData], (rawData) => rawData.results],
    }),
    actionToUrl(({ values }) => ({
        reloadData: () => {
            return [
                urls.explore(),
                { category: values.category, filters: values.filters ?? undefined },
                {},
                { replace: true },
            ]
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.explore()]: (_, { category, filters }) => {
            if (category && category !== values.category) {
                actions.setCategory(category)
            }
            if (filters && filters !== values.filters) {
                actions.setFilters(filters)
            }
            if (!category && !filters) {
                // came from a blank url after the logic was already loaded
                actions.setCategory(ExploreCategory.Events)
                actions.setFilters(null)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.reloadData()
    }),
])

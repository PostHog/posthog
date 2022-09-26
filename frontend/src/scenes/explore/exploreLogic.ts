import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import api from 'lib/api'
import type { exploreLogicType } from './exploreLogicType'
import { ExploreCategory } from '~/types'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

export const categories: Record<ExploreCategory, any> = {
    [ExploreCategory.Events]: 'Events',
    [ExploreCategory.People]: 'People',
    [ExploreCategory.Cohorts]: 'Cohorts',
    [ExploreCategory.Recordings]: 'Recordings',
}

export const categorySelectOptions = Object.entries(categories).map(([value, label]) => ({ value, label }))

export const endpoints: Record<ExploreCategory, any> = {
    [ExploreCategory.Events]: () => api.events.list({}),
    [ExploreCategory.People]: () => api.persons.list(),
    [ExploreCategory.Cohorts]: () => api.cohorts.list(),
    [ExploreCategory.Recordings]: () => api.sessionRecordings.list(),
}

export const exploreLogic = kea<exploreLogicType>([
    path(['scenes', 'explore', 'exploreLogic']),
    actions({ setCategory: (category: ExploreCategory) => ({ category }), reloadData: true }),
    reducers({
        category: [ExploreCategory.Events as ExploreCategory, { setCategory: (_, { category }) => category }],
    }),
    listeners(({ actions }) => ({
        setCategory: () => {
            actions.reloadData()
        },
    })),
    loaders(({ values }) => ({
        rawData: [
            { results: [] } as { results: any[]; next?: string },
            {
                reloadData: async (_, breakpoint) => {
                    const { category } = values
                    const results = await endpoints[category]()
                    breakpoint()
                    return results
                },
            },
        ],
    })),
    selectors({
        rows: [(s) => [s.rawData], (rawData) => rawData.results],
    }),
    afterMount(({ actions }) => {
        actions.reloadData()
    }),
    actionToUrl(({ values }) => ({
        reloadData: () => {
            const { category } = values
            return [urls.explore(), { category }, {}, { replace: true }]
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.explore()]: (_, { category }) => {
            if (category && category !== values.category) {
                actions.setCategory(category)
            }
            if (!category) {
                // came from a blank url after the logic was already loaded
                actions.setCategory(ExploreCategory.Events)
            }
        },
    })),
])

import { afterMount, connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { BasicListItem } from '../types'
import { InsightModel } from '~/types'
import { subscriptions } from 'kea-subscriptions'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import type { insightsSidebarLogicType } from './insightsType'
import { findSearchTermInItemName } from './utils'

export interface SearchMatch {
    indices: readonly [number, number][]
    key: string
}

export const insightsSidebarLogic = kea<insightsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'insightsSidebarLogic']),
    connect(() => ({
        values: [
            savedInsightsLogic,
            ['insights', 'insightsLoading'],
            sceneLogic,
            ['activeScene', 'sceneParams'],
            navigation3000Logic,
            ['searchTerm'],
        ],
        actions: [savedInsightsLogic, ['loadInsights', 'setSavedInsightsFilters']],
    })),
    selectors(({ values }) => ({
        isLoading: [(s) => [s.insightsLoading], (insightsLoading) => insightsLoading],
        // TODO: Load more!
        contents: [
            (s) => [s.relevantInsights],
            (relevantInsights) =>
                relevantInsights.map(
                    (insight) =>
                        ({
                            key: insight.short_id,
                            name: insight.name || insight.derived_name || 'Untitled',
                            isNamePlaceholder: !insight.name,
                            url: urls.insightView(insight.short_id),
                            searchMatch: findSearchTermInItemName(
                                insight.name || insight.derived_name || '',
                                values.searchTerm
                            ),
                            menuItems: [],
                        } as BasicListItem)
                ),
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams) => {
                return activeScene === Scene.Insight && sceneParams.params.shortId ? sceneParams.params.shortId : null
            },
        ],
        relevantInsights: [
            (s) => [s.insights],
            (insights): InsightModel[] => {
                return insights.results
            },
        ],
        // kea-typegen doesn't like selectors without deps, so searchTerm is just for appearances
        debounceSearch: [(s) => [s.searchTerm], () => true],
    })),
    subscriptions(({ actions }) => ({
        searchTerm: (searchTerm) => {
            actions.setSavedInsightsFilters({ search: searchTerm }, false, false)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadInsights(false)
    }),
])

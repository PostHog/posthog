import { afterMount, connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { BasicListItem } from '../types'
import Fuse from 'fuse.js'
import { InsightModel } from '~/types'
import { subscriptions } from 'kea-subscriptions'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'

import type { insightsSidebarLogicType } from './insightsSidebarLogicType'

// TODO: Server-side search!
const fuse = new Fuse<InsightModel>([], {
    keys: [{ name: 'name', weight: 2 }, 'description', 'tags'],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

export interface SearchMatch {
    indices: readonly [number, number][]
    key: string
}

export const insightsSidebarLogic = kea<insightsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'InsightsSidebarLogic']),
    connect({
        values: [savedInsightsLogic, ['insights', 'insightsLoading'], sceneLogic, ['activeScene', 'sceneParams']],
        actions: [savedInsightsLogic, ['loadInsights']],
    }),
    selectors(({}) => ({
        isLoading: [(s) => [s.insightsLoading], (insightsLoading) => insightsLoading],
        contents: [
            (s) => [s.relevantInsights],
            (relevantInsights) =>
                relevantInsights.map(
                    ([insight, matches]) =>
                        ({
                            key: insight.short_id,
                            name: insight.name || insight.derived_name || 'Untitled',
                            isNamePlaceholder: !insight.name,
                            url: urls.insightView(insight.short_id),
                            searchMatch: matches
                                ? {
                                      matchingFields: matches.map((match) => match.key),
                                      nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                                  }
                                : null,
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
            (s) => [s.insights, navigation3000Logic.selectors.searchTerm],
            (insights, searchTerm): [InsightModel, SearchMatch[] | null][] => {
                if (searchTerm) {
                    return fuse.search(searchTerm).map((result) => [result.item, result.matches as SearchMatch[]])
                }
                return insights.results.map((insight) => [insight, null])
            },
        ],
    })),
    subscriptions({
        insights: (insights) => {
            fuse.setCollection(insights.results)
        },
    }),
    afterMount(({ actions }) => {
        actions.loadInsights()
    }),
])

import { afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { SidebarCategory, BasicListItem } from '../types'
import { InsightModel } from '~/types'
import { subscriptions } from 'kea-subscriptions'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { INSIGHTS_PER_PAGE, savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import type { insightsSidebarLogicType } from './insightsType'
import { findSearchTermInItemName } from './utils'
import { deleteWithUndo } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { api } from '@posthog/apps-common'
import { insightsModel } from '~/models/insightsModel'

export const insightsSidebarLogic = kea<insightsSidebarLogicType>([
    path(['layout', 'navigation-3000', 'sidebars', 'insightsSidebarLogic']),
    connect(() => ({
        values: [
            savedInsightsLogic,
            ['insights', 'insightsLoading', 'paramsFromFilters'],
            sceneLogic,
            ['activeScene', 'sceneParams'],
            navigation3000Logic,
            ['searchTerm'],
        ],
        actions: [savedInsightsLogic, ['loadInsights', 'setSavedInsightsFilters', 'duplicateInsight']],
    })),
    reducers(() => ({
        infiniteInsights: [
            [] as (InsightModel | undefined)[],
            {
                [savedInsightsLogic.actionTypes.loadInsightsSuccess]: (state, { insights }) => {
                    // Reset array if offset is 0
                    const items: (InsightModel | undefined)[] = insights.offset === 0 ? [] : state.slice()
                    for (let i = 0; i < insights.results.length; i++) {
                        items[insights.offset + i] = insights.results[i]
                    }
                    return items
                },
            },
        ],
    })),
    selectors(({ actions, values, cache }) => ({
        contents: [
            (s) => [s.insights, s.infiniteInsights, s.insightsLoading, teamLogic.selectors.currentTeamId],
            (insights, infiniteInsights, insightsLoading, currentTeamId) => [
                {
                    key: 'insights',
                    noun: 'insight',
                    onAdd: urls.insightNew(),
                    items: infiniteInsights.map(
                        (insight) =>
                            insight &&
                            ({
                                key: insight.short_id,
                                name: insight.name || insight.derived_name || 'Untitled',
                                isNamePlaceholder: !insight.name,
                                url: urls.insightView(insight.short_id),
                                searchMatch: findSearchTermInItemName(
                                    insight.name || insight.derived_name || '',
                                    values.searchTerm
                                ),
                                menuItems: (initiateRename) => [
                                    {
                                        items: [
                                            {
                                                to: urls.insightEdit(insight.short_id),
                                                label: 'Edit',
                                            },
                                            {
                                                onClick: () => {
                                                    actions.duplicateInsight(insight)
                                                },
                                                label: 'Duplicate',
                                            },
                                        ],
                                    },
                                    {
                                        items: [
                                            {
                                                onClick: initiateRename,
                                                label: 'Rename',
                                                keyboardShortcut: ['enter'],
                                            },
                                            {
                                                onClick: () => {
                                                    deleteWithUndo({
                                                        object: insight,
                                                        endpoint: `projects/${currentTeamId}/insights`,
                                                        callback: actions.loadInsights,
                                                    })
                                                },
                                                status: 'danger',
                                                label: 'Delete insight',
                                            },
                                        ],
                                    },
                                ],
                                onRename: async (newName) => {
                                    const updatedItem = await api.update(
                                        `api/projects/${teamLogic.values.currentTeamId}/insights/${insight.id}`,
                                        {
                                            name: newName,
                                        }
                                    )
                                    insightsModel.actions.renameInsightSuccess(updatedItem)
                                },
                            } as BasicListItem)
                    ),
                    loading: insightsLoading,
                    remote: {
                        isItemLoaded: (index) => !!(cache.requestedInsights[index] || infiniteInsights[index]),
                        loadMoreItems: async (startIndex) => {
                            for (let i = startIndex; i < startIndex + INSIGHTS_PER_PAGE; i++) {
                                cache.requestedInsights[i] = true
                            }
                            await savedInsightsLogic.actions.setSavedInsightsFilters(
                                { page: Math.floor(startIndex / INSIGHTS_PER_PAGE) + 1 },
                                true,
                                false
                            )
                        },
                        itemCount: insights.count,
                        minimumBatchSize: INSIGHTS_PER_PAGE,
                    },
                } as SidebarCategory,
            ],
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams): [string, string] | null => {
                return activeScene === Scene.Insight && sceneParams.params.shortId
                    ? ['insights', sceneParams.params.shortId]
                    : null
            },
        ],
        // kea-typegen doesn't like selectors without deps, so searchTerm is just for appearances
        debounceSearch: [(s) => [s.searchTerm], () => true],
    })),
    listeners(({ values, cache }) => ({
        loadInsights: () => {
            if (!values.paramsFromFilters.offset) {
                cache.requestedInsights = []
            }
        },
    })),
    subscriptions(({ actions }) => ({
        searchTerm: (searchTerm) => {
            actions.setSavedInsightsFilters({ search: searchTerm }, false, false)
        },
    })),
    afterMount(({ cache }) => {
        cache.requestedInsights = []
    }),
])

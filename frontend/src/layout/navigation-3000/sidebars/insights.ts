import { afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { deleteInsightWithUndo } from 'lib/utils/deleteWithUndo'
import { insightsApi } from 'scenes/insights/utils/api'
import { INSIGHTS_PER_PAGE, savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { insightsModel } from '~/models/insightsModel'
import { QueryBasedInsightModel } from '~/types'

import { BasicListItem, SidebarCategory } from '../types'
import type { insightsSidebarLogicType } from './insightsType'
import { findSearchTermInItemName } from './utils'

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
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [savedInsightsLogic, ['loadInsights', 'setSavedInsightsFilters', 'duplicateInsight']],
    })),
    reducers(() => ({
        infiniteInsights: [
            [] as (QueryBasedInsightModel | undefined)[],
            {
                [savedInsightsLogic.actionTypes.loadInsightsSuccess]: (state, { insights }) => {
                    // Reset array if offset is 0
                    const items: (QueryBasedInsightModel | undefined)[] = insights.offset === 0 ? [] : state.slice()
                    for (let i = 0; i < insights.results.length; i++) {
                        items[insights.offset + i] = insights.results[i]
                    }
                    return items
                },
            },
        ],
    })),
    selectors(({ actions, values, cache }) => ({
        queryBasedInsightSaving: [
            (s) => [s.featureFlags],
            (featureFlags) => !!featureFlags[FEATURE_FLAGS.QUERY_BASED_INSIGHTS_SAVING],
        ],
        contents: [
            (s) => [s.insights, s.infiniteInsights, s.insightsLoading, teamLogic.selectors.currentTeamId],
            (insights, infiniteInsights, insightsLoading, currentTeamId) => [
                {
                    key: 'insights',
                    noun: 'insight',
                    onAdd: urls.insightNew(),
                    items: infiniteInsights.map((insight) => {
                        if (!insight) {
                            return undefined
                        }

                        return {
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
                                                void deleteInsightWithUndo({
                                                    object: insight,
                                                    endpoint: `projects/${currentTeamId}/insights`,
                                                    callback: actions.loadInsights,
                                                    options: {
                                                        writeAsQuery: values.queryBasedInsightSaving,
                                                        readAsQuery: true,
                                                    },
                                                })
                                            },
                                            status: 'danger',
                                            label: 'Delete insight',
                                        },
                                    ],
                                },
                            ],
                            onRename: async (newName) => {
                                const updatedItem = await insightsApi.update(
                                    insight.id,
                                    { name: newName },
                                    { writeAsQuery: values.queryBasedInsightSaving, readAsQuery: false }
                                )
                                insightsModel.actions.renameInsightSuccess(updatedItem)
                            },
                        } as BasicListItem
                    }),
                    loading: insightsLoading,
                    remote: {
                        isItemLoaded: (index) => !!(cache.requestedInsights[index] || infiniteInsights[index]),
                        loadMoreItems: async (startIndex) => {
                            for (let i = startIndex; i < startIndex + INSIGHTS_PER_PAGE; i++) {
                                cache.requestedInsights[i] = true
                            }
                            await savedInsightsLogic.asyncActions.setSavedInsightsFilters(
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

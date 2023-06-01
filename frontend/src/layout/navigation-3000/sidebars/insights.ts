import { afterMount, connect, kea, path, selectors } from 'kea'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { SidebarCategory, BasicListItem } from '../types'
import { InsightModel } from '~/types'
import { subscriptions } from 'kea-subscriptions'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import type { insightsSidebarLogicType } from './insightsType'
import { findSearchTermInItemName } from './utils'
import { deleteWithUndo } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { api } from '@posthog/apps-common'
import { insightsModel } from '~/models/insightsModel'

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
        actions: [savedInsightsLogic, ['loadInsights', 'setSavedInsightsFilters', 'duplicateInsight']],
    })),
    selectors(({ actions, values }) => ({
        contents: [
            (s) => [s.relevantInsights, s.insightsLoading, teamLogic.selectors.currentTeamId],
            (relevantInsights, insightsLoading, currentTeamId) => [
                {
                    key: 'insights',
                    title: 'Insights',
                    items: relevantInsights.map(
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
                    // FIXME: Add remote
                } as SidebarCategory,
            ],
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

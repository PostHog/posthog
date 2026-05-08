import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { MaxContextInput } from 'scenes/max/maxTypes'
import { projectLogic } from 'scenes/projectLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { Breadcrumb, DashboardBasicType, InsightModel, QueryBasedInsightModel } from '~/types'

export type RecentItem =
    | (QueryBasedInsightModel & { itemType: 'insight' })
    | (DashboardBasicType & { itemType: 'dashboard' })

import type { projectHomepageLogicType } from './projectHomepageLogicType'

export const projectHomepageLogic = kea<projectHomepageLogicType>([
    path(['scenes', 'project-homepage', 'projectHomepageLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], dashboardsModel, ['rawDashboards', 'dashboardsLoading']],
    })),

    actions({
        toggleInsightExpanded: (insightShortId: string) => ({ insightShortId }),
    }),

    reducers({
        expandedInsightIds: [
            new Set<string>(),
            {
                toggleInsightExpanded: (state, { insightShortId }) => {
                    const next = new Set(state)
                    next.has(insightShortId) ? next.delete(insightShortId) : next.add(insightShortId)
                    return next
                },
            },
        ],
    }),

    loaders(({ values }) => ({
        recentInsights: [
            [] as QueryBasedInsightModel[],
            {
                loadRecentInsights: async () => {
                    const insights = await api.get<InsightModel[]>(
                        `api/environments/${values.currentProjectId}/insights/my_last_viewed`
                    )
                    return insights.map((legacyInsight) => getQueryBasedInsightModel(legacyInsight))
                },
            },
        ],
    })),

    selectors({
        maxContext: [
            () => [],
            // Context is only added explicitly via the @Context button.
            (): MaxContextInput[] => [],
        ],
        recentItems: [
            (s) => [s.recentInsights, s.recentDashboards],
            (recentInsights, recentDashboards): RecentItem[] => {
                return [
                    ...recentInsights.map((i) => ({ ...i, itemType: 'insight' as const })),
                    ...recentDashboards.map((d) => ({ ...d, itemType: 'dashboard' as const })),
                ]
                    .sort(
                        (a, b) => new Date(b.last_viewed_at || 0).getTime() - new Date(a.last_viewed_at || 0).getTime()
                    )
                    .slice(0, 5)
            },
        ],
        recentDashboards: [
            (s) => [s.rawDashboards],
            (rawDashboards): DashboardBasicType[] => {
                return Object.values(rawDashboards).filter((d) => d.last_viewed_at && !d.deleted)
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'home',
                    name: 'Home',
                    iconType: 'home',
                },
            ],
        ],
    }),
])

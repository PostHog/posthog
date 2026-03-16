import { BuiltLogic, actions, beforeUnmount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardLogicProps, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import {
    Breadcrumb,
    DashboardBasicType,
    DashboardPlacement,
    DashboardType,
    InsightModel,
    QueryBasedInsightModel,
} from '~/types'

export type RecentItem =
    | (QueryBasedInsightModel & { itemType: 'insight' })
    | (DashboardBasicType & { itemType: 'dashboard' })

import type { projectHomepageLogicType } from './projectHomepageLogicType'

export const projectHomepageLogic = kea<projectHomepageLogicType>([
    path(['scenes', 'project-homepage', 'projectHomepageLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam'],
            projectLogic,
            ['currentProjectId'],
            dashboardsModel,
            ['rawDashboards', 'dashboardsLoading'],
            featureFlagLogic,
            ['featureFlags'],
        ],
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
        primaryDashboardId: [() => [teamLogic.selectors.currentTeam], (currentTeam) => currentTeam?.primary_dashboard],
        dashboardLogicProps: [
            (s) => [s.primaryDashboardId],
            (primaryDashboardId): DashboardLogicProps | null =>
                primaryDashboardId
                    ? {
                          id: primaryDashboardId,
                          placement: DashboardPlacement.ProjectHomepage,
                      }
                    : null,
        ],
        maxContext: [
            (s) => [
                s.featureFlags,
                (state) => {
                    // Get the dashboard from the mounted dashboardLogic
                    const dashboardLogicProps = s.dashboardLogicProps(state)
                    if (!dashboardLogicProps) {
                        return null
                    }
                    const logic = dashboardLogic.findMounted(dashboardLogicProps)
                    if (!logic) {
                        return null
                    }
                    return logic.selectors.dashboard(state)
                },
            ],
            (
                featureFlags: Record<string, any>,
                dashboard: DashboardType<QueryBasedInsightModel> | null
            ): MaxContextInput[] => {
                // In AI-first mode, context should only be added explicitly via @Context button
                if (featureFlags[FEATURE_FLAGS.AI_FIRST]) {
                    return []
                }
                if (!dashboard) {
                    return []
                }
                return [createMaxContextHelpers.dashboard(dashboard)]
            },
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

    subscriptions(({ cache }) => ({
        dashboardLogicProps: (dashboardLogicProps) => {
            if (dashboardLogicProps) {
                const unmount = (dashboardLogic(dashboardLogicProps) as BuiltLogic).mount()
                cache.unmountDashboardLogic?.()
                cache.unmountDashboardLogic = unmount
            } else if (cache.unmountDashboardLogic) {
                cache.unmountDashboardLogic?.()
                cache.unmountDashboardLogic = null
            }
        },
    })),

    beforeUnmount(({ cache }) => {
        cache.unmountDashboardLogic?.()
        cache.unmountDashboardLogic = null
    }),
])

import { BuiltLogic, actions, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardLogicProps, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { Breadcrumb, DashboardPlacement, DashboardType, InsightModel, QueryBasedInsightModel } from '~/types'

import type { projectHomepageLogicType } from './projectHomepageLogicType'

export const projectHomepageLogic = kea<projectHomepageLogicType>([
    path(['scenes', 'project-homepage', 'projectHomepageLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam'], projectLogic, ['currentProjectId'], featureFlagLogic, ['featureFlags']],
    })),

    actions({
        toggleInsightExpanded: (insightShortId: string) => ({ insightShortId }),
        openFirstEventCreateEventModal: true,
        closeFirstEventCreateEventModal: true,
        clickFirstEventBannerCTA: true,
        reportFirstEventBannerImpression: true,
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
        isFirstEventCreateEventModalOpen: [
            false,
            {
                openFirstEventCreateEventModal: () => true,
                closeFirstEventCreateEventModal: () => false,
            },
        ],
        hasSentFirstEventBannerImpression: [
            false,
            {
                reportFirstEventBannerImpression: () => true,
            },
        ],
    }),

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
            (dashboard: DashboardType<QueryBasedInsightModel> | null): MaxContextInput[] => {
                if (!dashboard) {
                    return []
                }
                return [createMaxContextHelpers.dashboard(dashboard)]
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
        isFirstEventBannerEligible: [
            (s) => [s.currentTeam],
            (currentTeam): boolean => !!currentTeam && !currentTeam.is_demo && !currentTeam.ingested_event,
        ],
        isFirstEventBannerEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => featureFlags[FEATURE_FLAGS.FIRST_EVENT_BANNER] === true,
        ],
        shouldShowFirstEventBanner: [
            (s) => [s.isFirstEventBannerEligible, s.isFirstEventBannerEnabled],
            (isEligible, isEnabled): boolean => isEligible && isEnabled,
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

    listeners(({ actions, values }) => ({
        clickFirstEventBannerCTA: () => {
            posthog.capture('banner.cta_click', {
                banner: 'first_event',
                location: 'project_homepage',
                feature_flag: FEATURE_FLAGS.FIRST_EVENT_BANNER,
            })
            actions.openFirstEventCreateEventModal()
        },
        reportFirstEventBannerImpression: () => {
            if (values.hasSentFirstEventBannerImpression) {
                return
            }
            posthog.capture('banner.impression', {
                banner: 'first_event',
                location: 'project_homepage',
                feature_flag: FEATURE_FLAGS.FIRST_EVENT_BANNER,
            })
        },
    })),

    subscriptions(({ actions, values }) => ({
        shouldShowFirstEventBanner: (shouldShow) => {
            if (shouldShow && !values.hasSentFirstEventBannerImpression) {
                actions.reportFirstEventBannerImpression()
            }
        },
    })),

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

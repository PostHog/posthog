import { afterMount, connect, kea, path, selectors } from 'kea'

import { projectHomepageLogicType } from './projectHomepageLogicType'
import { teamLogic } from 'scenes/teamLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { DashboardPlacement, InsightModel, PersonType } from '~/types'
import api from 'lib/api'
import { subscriptions } from 'kea-subscriptions'
import { loaders } from 'kea-loaders'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export const projectHomepageLogic = kea<projectHomepageLogicType>([
    path(['scenes', 'project-homepage', 'projectHomepageLogic']),
    connect({
        values: [teamLogic, ['currentTeamId', 'currentTeam']],
        actions: [eventUsageLogic, ['reportTeamHasIngestedEvents']],
    }),

    selectors({
        primaryDashboardId: [() => [teamLogic.selectors.currentTeam], (currentTeam) => currentTeam?.primary_dashboard],
        dashboardLogic: [
            (s) => [s.primaryDashboardId],
            (primaryDashboardId): ReturnType<typeof dashboardLogic.build> | null =>
                dashboardLogic({
                    id: primaryDashboardId ?? undefined,
                    placement: DashboardPlacement.ProjectHomepage,
                }),
        ],
    }),

    loaders(({ values }) => ({
        recentInsights: [
            [] as InsightModel[],
            {
                loadRecentInsights: async () => {
                    const response = await api.get(
                        `api/projects/${values.currentTeamId}/insights/?my_last_viewed=true&order=-my_last_viewed_at`
                    )
                    return response.results
                },
            },
        ],
        persons: [
            [] as PersonType[],
            {
                loadPersons: async () => {
                    const response = await api.get(`api/person/`)
                    return response.results
                },
            },
        ],
    })),

    subscriptions(({ cache }: projectHomepageLogicType) => ({
        dashboardLogic: (logic: ReturnType<typeof dashboardLogic.build>) => {
            cache.unmount?.()
            cache.unmount = logic ? logic.mount() : null
        },
    })),

    afterMount(({ cache, actions, values }) => {
        cache.unmount?.()
        actions.loadRecentInsights()
        actions.loadPersons()
        // For Onboarding 1's experiment, we are tracking whether a team has ingested events on the client side
        // because experiments doesn't support this yet in other libraries
        if (values.currentTeam?.ingested_event) {
            actions.reportTeamHasIngestedEvents()
        }
    }),
])

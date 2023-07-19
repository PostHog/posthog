import { connect, kea, selectors, path } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import { DashboardPlacement } from '~/types'
import { DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'

import type { groupDashboardLogicType } from './groupDashboardLogicType'

export const groupDashboardLogic = kea<groupDashboardLogicType>([
    path(['scenes', 'groups', 'groupDashboardLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    selectors(() => ({
        groupDashboardId: [
            (s) => [s.currentTeam],
            (currentTeam) => {
                return currentTeam?.scene_dashboards?.[Scene.Group] || null
            },
        ],
        dashboardLogicProps: [
            (s) => [s.groupDashboardId],
            (groupDashboardId): DashboardLogicProps => ({
                id: groupDashboardId ?? undefined,
                placement: DashboardPlacement.Group,
            }),
        ],
    })),
])

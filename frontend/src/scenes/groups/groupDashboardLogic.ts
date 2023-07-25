import { connect, kea, selectors, path } from 'kea'

import { DashboardPlacement } from '~/types'
import { Scene } from 'scenes/sceneTypes'

import type { groupDashboardLogicType } from './groupDashboardLogicType'
import { DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { userLogic } from 'scenes/userLogic'

export const groupDashboardLogic = kea<groupDashboardLogicType>([
    path(['scenes', 'groups', 'groupDashboardLogic']),
    connect({
        values: [userLogic, ['user']],
    }),
    selectors(() => ({
        groupDashboardId: [
            (s) => [s.user],
            (user) => {
                const currentDashboard = user?.scene_dashboard_choices?.find(
                    (choice) => choice.scene === Scene.Group
                )?.dashboard
                return typeof currentDashboard === 'number' ? currentDashboard : currentDashboard?.id
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

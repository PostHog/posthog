import { connect, kea, path, selectors } from 'kea'
import { DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { DashboardPlacement } from '~/types'

import type { groupDashboardLogicType } from './groupDashboardLogicType'

export const groupDashboardLogic = kea<groupDashboardLogicType>([
    path(['scenes', 'groups', 'groupDashboardLogic']),
    connect({
        values: [userLogic, ['user']],
    }),
    selectors(() => ({
        groupDashboardId: [
            (s) => [s.user],
            (user) => {
                const currentDashboard = user?.scene_personalisation?.find(
                    (choice) => choice.scene === Scene.Group
                )?.dashboard
                return typeof currentDashboard === 'number' ? currentDashboard : currentDashboard?.id
            },
        ],
        dashboardLogicProps: [
            (s) => [s.groupDashboardId],
            (groupDashboardId): DashboardLogicProps | null =>
                groupDashboardId
                    ? {
                          id: groupDashboardId,
                          placement: DashboardPlacement.Group,
                      }
                    : null,
        ],
    })),
])

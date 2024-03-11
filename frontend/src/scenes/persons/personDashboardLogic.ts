import { connect, kea, path, selectors } from 'kea'
import { DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { DashboardPlacement, PersonType } from '~/types'

import type { personDashboardLogicType } from './personDashboardLogicType'

export interface PersonDashboardLogicProps {
    person: PersonType
}

export const personDashboardLogic = kea<personDashboardLogicType>([
    path(['scenes', 'persons', 'personDashboardLogic']),
    connect({
        values: [userLogic, ['user']],
    }),
    selectors(() => ({
        personDashboardId: [
            (s) => [s.user],
            (user) => {
                const currentDashboard = user?.scene_personalisation?.find(
                    (choice) => choice.scene === Scene.Person
                )?.dashboard
                return typeof currentDashboard === 'number' ? currentDashboard : currentDashboard?.id
            },
        ],
        dashboardLogicProps: [
            (s) => [s.personDashboardId],
            (personDashboardId): DashboardLogicProps | null =>
                personDashboardId
                    ? {
                          id: personDashboardId,
                          placement: DashboardPlacement.Person,
                      }
                    : null,
        ],
    })),
])

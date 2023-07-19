import { connect, kea, selectors, path } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import type { personDashboardLogicType } from './personDashboardLogicType'
import { DashboardPlacement, PersonType } from '~/types'
import { DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'

export interface PersonDashboardLogicProps {
    person: PersonType
}

export const personDashboardLogic = kea<personDashboardLogicType>([
    path(['scenes', 'persons', 'personDashboardLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    selectors(() => ({
        personDashboardId: [
            (s) => [s.currentTeam],
            (currentTeam) => {
                return currentTeam?.scene_dashboards?.[Scene.Person] || null
            },
        ],
        dashboardLogicProps: [
            (s) => [s.personDashboardId],
            (personDashboardId): DashboardLogicProps => ({
                id: personDashboardId ?? undefined,
                placement: DashboardPlacement.Person,
            }),
        ],
    })),
])

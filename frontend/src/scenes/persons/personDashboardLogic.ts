import { connect, kea, selectors, path } from 'kea'

import type { personDashboardLogicType } from './personDashboardLogicType'
import { DashboardPlacement, HogQLPropertyFilter, PersonType, PropertyFilterType } from '~/types'
import { DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { Scene } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

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
            (personDashboardId): ((p: PersonType) => DashboardLogicProps) => {
                return (person: PersonType): DashboardLogicProps => {
                    // TODO: needs https://github.com/PostHog/posthog/pull/16653 so we can filter by person ID
                    const hogQLPersonFilter = `person.properties.email = '${person.properties.email}'`
                    const desired: HogQLPropertyFilter = {
                        type: PropertyFilterType.HogQL,
                        key: hogQLPersonFilter,
                    }

                    return {
                        id: personDashboardId ?? undefined,
                        placement: DashboardPlacement.Person,
                        temporaryFilters: { properties: [desired] },
                    }
                }
            },
        ],
    })),
])

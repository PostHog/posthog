import { useActions, useValues } from 'kea'
import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useEffect } from 'react'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { dashboardLogic, DashboardLogicProps } from 'scenes/dashboard/dashboardLogic'
import { personDashboardLogic } from 'scenes/persons/personDashboardLogic'
import { Scene } from 'scenes/sceneTypes'

import { HogQLPropertyFilter, PersonType, PropertyFilterType } from '~/types'

export function PersonDashboard({ person }: { person: PersonType }): JSX.Element {
    const { showSceneDashboardChoiceModal } = useActions(sceneDashboardChoiceModalLogic({ scene: Scene.Person }))
    const { dashboardLogicProps } = useValues(personDashboardLogic)

    return (
        <>
            {dashboardLogicProps?.id !== undefined ? (
                <PersonDashboardExisting person={person} dashboardLogicProps={dashboardLogicProps} />
            ) : (
                <SceneDashboardChoiceRequired
                    open={() => {
                        showSceneDashboardChoiceModal()
                    }}
                    scene={Scene.Person}
                />
            )}
            <SceneDashboardChoiceModal scene={Scene.Person} />
        </>
    )
}

function PersonDashboardExisting({
    person,
    dashboardLogicProps,
}: {
    person: PersonType
    dashboardLogicProps: DashboardLogicProps
}): JSX.Element {
    const { showSceneDashboardChoiceModal } = useActions(sceneDashboardChoiceModalLogic({ scene: Scene.Person }))
    const { dashboard } = useValues(dashboardLogic(dashboardLogicProps))
    const { setProperties } = useActions(dashboardLogic(dashboardLogicProps))

    useEffect(() => {
        if (dashboard && person) {
            // `dashboard?.filters.properties` is typed as `any` but it's a list...
            const current = Array.isArray(dashboard?.filters.properties) ? dashboard?.filters.properties : []
            // TODO: needs https://github.com/PostHog/posthog/pull/16653 so we can filter by person ID
            const hogQLPersonFilter = `person.properties.email = '${person.properties.email}'`
            const desired: HogQLPropertyFilter = {
                type: PropertyFilterType.HogQL,
                key: hogQLPersonFilter,
            }

            const hasDesired = current.some(
                (item) => item.type === PropertyFilterType.HogQL && item.key === hogQLPersonFilter
            )
            if (!hasDesired) {
                setProperties([
                    ...current.filter(
                        (item) =>
                            item.type === PropertyFilterType.HogQL && !item.key.startsWith('person.properties.email')
                    ),
                    desired,
                ])
            }
        }
    }, [dashboard, person])

    return (
        <>
            <div className="flex items-center justify-end mb-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    data-attr="person-dashboard-change-dashboard"
                    onClick={showSceneDashboardChoiceModal}
                >
                    Change dashboard
                </LemonButton>
            </div>
            <Dashboard id={dashboardLogicProps.id.toString()} placement={dashboardLogicProps.placement} />
        </>
    )
}

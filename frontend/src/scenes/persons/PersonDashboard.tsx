import { HogQLPropertyFilter, PersonType, PropertyFilterType } from '~/types'
import { Scene } from 'scenes/sceneTypes'
import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { useActions, useValues } from 'kea'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { personDashboardLogic } from 'scenes/persons/personDashboardLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { useEffect } from 'react'

export function PersonDashboard({ person }: { person: PersonType }): JSX.Element {
    const { showSceneDashboardChoiceModal } = useActions(sceneDashboardChoiceModalLogic({ scene: Scene.Person }))
    const { dashboardLogicProps } = useValues(personDashboardLogic)

    // TODO: needs https://github.com/PostHog/posthog/pull/16653 so we can filter by person ID
    const { dashboard } = useValues(dashboardLogic(dashboardLogicProps))
    const { setProperties } = useActions(dashboardLogic(dashboardLogicProps))
    useEffect(() => {
        if (dashboard && person) {
            // `dashboard?.filters.properties` is typed as `any` but it's a list...
            const current = Array.isArray(dashboard?.filters.properties) ? dashboard?.filters.properties : []
            const hogQLPersonFilter = `person.properties.email = '${person.properties.email}'`
            const desired: HogQLPropertyFilter = {
                type: PropertyFilterType.HogQL,
                key: hogQLPersonFilter,
            }

            const hasFilter = current.some(
                (item) => item.type === PropertyFilterType.HogQL && item.key.startsWith(`person.properties.email =`)
            )
            if (!hasFilter) {
                setProperties([...current, desired])
            }
        }
    }, [dashboard, person])

    return (
        <>
            {dashboardLogicProps.id !== undefined ? (
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

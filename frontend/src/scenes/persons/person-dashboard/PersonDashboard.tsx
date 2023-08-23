import { PersonType } from '~/types'
import { Scene } from 'scenes/sceneTypes'
import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { useActions, useValues } from 'kea'
import { Dashboard } from 'scenes/dashboard/Dashboard'
import { personDashboardLogic } from 'scenes/persons/person-dashboard/personDashboardLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

export function PersonDashboard({ person }: { person: PersonType }): JSX.Element {
    const { showSceneDashboardChoiceModal } = useActions(sceneDashboardChoiceModalLogic({ scene: Scene.Person }))
    const { dashboardLogicProps } = useValues(personDashboardLogic)
    const dashboardLogicPropsForPerson = dashboardLogicProps(person)

    // TODO this component requires https://github.com/PostHog/posthog/pull/16653
    //  to be able to properly filter for persons

    if (!person.properties.email) {
        return (
            <div className="empty-state-container flex flex-col items-center">
                <h1>You can only show a person dashboard for a person with an email address</h1>
            </div>
        )
    }

    return (
        <>
            {dashboardLogicPropsForPerson.id !== undefined ? (
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
                    <Dashboard
                        id={dashboardLogicPropsForPerson.id.toString()}
                        placement={dashboardLogicPropsForPerson.placement}
                        temporaryFilters={dashboardLogicPropsForPerson.temporaryFilters}
                    />
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

import { PersonType } from '~/types'
import { Scene } from 'scenes/sceneTypes'
import { SceneDashboardChoiceRequired } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceRequired'
import { SceneDashboardChoiceModal } from 'lib/components/SceneDashboardChoice/SceneDashboardChoiceModal'
import { sceneDashboardChoiceModalLogic } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { useActions } from 'kea'

export function PersonDashboard({}: { person: PersonType }): JSX.Element {
    const { showSceneDashboardChoiceModal } = useActions(sceneDashboardChoiceModalLogic({ scene: Scene.Person }))

    return (
        <>
            <SceneDashboardChoiceRequired
                open={() => {
                    showSceneDashboardChoiceModal()
                }}
                scene={Scene.Person}
            />
            <SceneDashboardChoiceModal scene={Scene.Person} />
        </>
    )
}

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import {
    DashboardCompatibleScenes,
    sceneDescription,
} from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { Scene } from 'scenes/sceneTypes'
import { SceneIcon } from 'lib/components/SceneDashboardChoice/SceneIcon'

export function SceneDashboardChoiceRequired(props: {
    open: () => void
    scene: DashboardCompatibleScenes
}): JSX.Element {
    if (props.scene === Scene.ProjectHomepage) {
        // homepage is a _team_ choice, not a personal choice
        return (
            <div className="empty-state-container flex flex-col items-center">
                <h1>
                    <SceneIcon scene={props.scene} size={'large'} /> There isn’t a default dashboard set for{' '}
                    {sceneDescription[props.scene]}
                </h1>

                <p className="mb-4">
                    Default dashboards are shown to everyone in the project. When you set a default, it’ll show up here.
                </p>

                <LemonButton
                    type="primary"
                    data-attr={`${props.scene}-choose-dashboard-from-empty`}
                    onClick={props.open}
                >
                    Select a dashboard
                </LemonButton>
            </div>
        )
    }
    return (
        // persons and groups are personal choices
        <div className="empty-state-container flex flex-col items-center">
            <h1>
                <SceneIcon scene={props.scene} size={'large'} /> You haven't set a dashboard for the{' '}
                {sceneDescription[props.scene]} page
            </h1>

            <p className="mb-4">You can choose a personalised dashboard to show on this page.</p>

            <LemonButton type="primary" data-attr={`${props.scene}-choose-dashboard-from-empty`} onClick={props.open}>
                Select a dashboard
            </LemonButton>
        </div>
    )
}

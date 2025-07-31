import { SceneIcon } from 'lib/components/SceneDashboardChoice/SceneIcon'
import {
    DashboardCompatibleScenes,
    sceneDescription,
} from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Scene } from 'scenes/sceneTypes'

export function SceneDashboardChoiceRequired(props: {
    open: () => void
    scene: DashboardCompatibleScenes
}): JSX.Element {
    return (
        <div className="empty-state-container flex flex-col items-center">
            <h1>
                <SceneIcon scene={props.scene} size="large" /> There isn’t a{' '}
                {props.scene === Scene.ProjectHomepage ? <>default </> : null}dashboard set for{' '}
                {sceneDescription[props.scene]}
            </h1>
            {props.scene === Scene.ProjectHomepage ? (
                <p className="mb-4">
                    Default dashboards are shown to everyone in the project. When you set a default, it’ll show up here.
                </p>
            ) : null}
            <LemonButton type="primary" data-attr={`${props.scene}-choose-dashboard-from-empty`} onClick={props.open}>
                Select a dashboard
            </LemonButton>
        </div>
    )
}

import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'

import { featureManagementLogic } from './featureManagementLogic'

export const scene: SceneExport = {
    component: FeatureManagement,
    logic: featureManagementLogic,
}

export function FeatureManagement(): JSX.Element {
    const { activeScene, scenes } = useValues(featureManagementLogic)
    const { setActiveScene } = useActions(featureManagementLogic)

    return (
        <div className="flex gap-4">
            <ul className="w-1/6 space-y-px">
                {scenes.map((scene) => (
                    <li key={scene.id}>
                        <LemonButton
                            onClick={() => setActiveScene(scene)}
                            size="small"
                            fullWidth
                            active={activeScene.id === scene.id}
                        >
                            {scene.title}
                        </LemonButton>
                    </li>
                ))}
            </ul>
            <div className="w-5/6">{activeScene.component}</div>
        </div>
    )
}

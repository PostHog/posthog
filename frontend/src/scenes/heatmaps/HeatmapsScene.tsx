import { SceneExport } from 'scenes/sceneTypes'

import { HeatmapsBrowser } from './HeatmapsBrowser'
import { heatmapsSceneLogic } from './heatmapsSceneLogic'

export const scene: SceneExport = {
    component: HeatmapsScene,
    logic: heatmapsSceneLogic,
}

export function HeatmapsScene(): JSX.Element {
    return (
        <div>
            <HeatmapsBrowser />
        </div>
    )
}

import { logsSceneLogic } from 'scenes/logs/logsSceneLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: LogsScene,
    logic: logsSceneLogic,
}

export function LogsScene(): JSX.Element {
    return <div>draw the owl</div>
}

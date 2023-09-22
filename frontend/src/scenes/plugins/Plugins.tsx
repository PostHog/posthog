import './Plugins.scss'
import { pluginsLogic } from './pluginsLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { AppsScene } from './AppsScene'

export const scene: SceneExport = {
    component: Plugins,
    logic: pluginsLogic,
}

export function Plugins(): JSX.Element | null {
    return <AppsScene />
}

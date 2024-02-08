import { SceneExport } from 'scenes/sceneTypes'
import { sitesLogic } from 'scenes/sites/sitesLogic'

export function SitesScene(): JSX.Element {
    return (
        <div>
            <h1>Sites</h1>
        </div>
    )
}

export const scene: SceneExport = {
    component: SitesScene,
    logic: sitesLogic,
}

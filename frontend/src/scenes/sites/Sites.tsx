import type { SceneExport } from 'scenes/sceneTypes'

import { sitesLogic } from 'scenes/sites/sitesLogic'
import { useValues } from 'kea'

export const scene: SceneExport = {
    component: Sites,
    logic: sitesLogic,
}

export function Sites(): JSX.Element {
    const values = useValues(sitesLogic)
    return <div>Sites {JSON.stringify(values)}</div>
}

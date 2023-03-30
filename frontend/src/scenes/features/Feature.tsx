import { SceneExport } from 'scenes/sceneTypes'
import { featureLogic } from './featureLogic'

export const scene: SceneExport = {
    component: Feature,
    logic: featureLogic,
    paramsToProps: ({ params: { id } }): typeof featureLogic['props'] => ({
        id,
    }),
}

export function Feature(): JSX.Element {
    return <></>
}

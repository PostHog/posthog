import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: NewConnection,
    logic: newConnectionLogic,
    // paramsToProps: ({ params: { pluginConfigId } }) => ({ pluginConfigId: parseInt(pluginConfigId) ?? 0 }),
}

export function NewConnection(): JSX.Element {
    return <>Hi</>
}

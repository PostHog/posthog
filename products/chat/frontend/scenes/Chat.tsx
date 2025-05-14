import { SceneExport } from 'scenes/sceneTypes'

import { chatLogic } from './chatLogic'

export const scene: SceneExport = {
    component: Chat,
    logic: chatLogic,
}

export function Chat(): JSX.Element {
    return <>chat</>
}

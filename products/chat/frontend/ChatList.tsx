import { SceneExport } from 'scenes/sceneTypes'

import { chatListLogic } from './chatListLogic'

export const scene: SceneExport = {
    component: ChatList,
    logic: chatListLogic,
}

export function ChatList(): JSX.Element {
    return <>chat list</>
}

import { SceneExport } from 'scenes/sceneTypes'

import { ChatTabs } from '../components/ChatTabs'
import { chatLogic } from './chatLogic'
export const scene: SceneExport = {
    component: ChatSettings,
    logic: chatLogic,
}

export function ChatSettings(): JSX.Element {
    return (
        <>
            <ChatTabs activeTab="chat-settings" />
        </>
    )
}

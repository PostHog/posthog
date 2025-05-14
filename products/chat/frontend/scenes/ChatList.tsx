import { useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { ChatsList } from '../components/ChatsList'
import { ChatWindow } from '../components/ChatWindow'
import { EmptyState } from '../components/EmptyState'
import { chatListLogic } from './chatListLogic'

export const scene: SceneExport = {
    component: ChatList,
    logic: chatListLogic,
}

export function ChatList(): JSX.Element {
    const { selectedChatId, chats } = useValues(chatListLogic)

    if (chats.length === 0) {
        return <div className="flex flex-col items-center justify-center h-full">No chats yet</div>
    }

    return (
        <div className="flex h-full gap-2">
            {/* Left: Chat list */}
            <div className="w-80 overflow-y-auto h-full">
                <ChatsList />
            </div>
            {/* Right: Chat view */}
            <main className="flex-1 flex flex-col h-full">
                <div className="flex-1 overflow-y-auto">{!selectedChatId ? <EmptyState /> : <ChatWindow />}</div>
            </main>
        </div>
    )
}

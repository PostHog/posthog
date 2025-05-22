import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { ChatsList } from '../components/ChatsList'
import { ChatTabs } from '../components/ChatTabs'
import { ChatWindow } from '../components/ChatWindow'
import { EmptyState } from '../components/EmptyState'
import { PickChatBlock } from '../components/PickChatBlock'
import { chatListLogic } from './chatListLogic'
export const scene: SceneExport = {
    component: ChatList,
    logic: chatListLogic,
}

export function ChatList(): JSX.Element {
    const { selectedChatId, chats } = useValues(chatListLogic)
    const { loadChats } = useActions(chatListLogic)

    const displayableChats = chats.filter((chat) => chat.messages && chat.messages.length > 0)

    const hasMessagesInDisplayableChats = displayableChats.some((chat) => chat.messages.length > 0)

    useEffect(() => {
        const intervalId = setInterval(() => {
            loadChats()
        }, 1000)

        return () => clearInterval(intervalId)
    }, [])

    /** If there are no chats, show the empty state */
    if (chats.length === 0 || !hasMessagesInDisplayableChats) {
        return (
            <>
                <ChatTabs activeTab="chat-list" />
                <EmptyState />
            </>
        )
    }

    return (
        <>
            <ChatTabs activeTab="chat-list" />
            <div className="flex gap-2 h-[calc(100vh-10rem)]">
                {/* Left: Chat list */}
                <div className="w-80 overflow-y-auto h-full">
                    <ChatsList />
                </div>
                {/* Right: Chat view */}
                <main className="flex-1 flex flex-col h-full">
                    <div className="flex-1 overflow-y-auto">{!selectedChatId ? <PickChatBlock /> : <ChatWindow />}</div>
                </main>
            </div>
        </>
    )
}

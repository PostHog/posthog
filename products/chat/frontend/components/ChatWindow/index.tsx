import { IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useEffect, useRef } from 'react'

import { chatListLogic } from '../../scenes/chatListLogic'
import { ChatInput } from './ChatInput'
import { Message } from './Message'

export function ChatWindow(): JSX.Element {
    const { selectedChatId, chats } = useValues(chatListLogic)
    const { setSelectedChatId } = useActions(chatListLogic)

    const messagesEndRef = useRef<HTMLDivElement>(null) // Ref for the bottom of the message list
    const messagesContainerRef = useRef<HTMLDivElement>(null) // Ref for the scrollable container

    const chat = chats.find((c) => c.id === selectedChatId)

    // Scroll to bottom effect
    useEffect(() => {
        if (messagesContainerRef.current) {
            messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight
        }
    }, [chat?.messages, selectedChatId]) // Rerun when messages or selected chat changes

    return (
        <div className="bg-white h-full flex flex-col border border-gray-200 rounded relative pb-16">
            <div className="flex flex-col gap-2 h-full p-4">
                <div className="flex items-center justify-end border-b border-gray-200 pb-2 mb-2">
                    <LemonButton icon={<IconX />} size="xsmall" onClick={() => setSelectedChatId(null)} />
                </div>
                <div ref={messagesContainerRef} className="overflow-y-auto h-full">
                    {chat?.messages.map((msg) => (
                        <Message key={msg.id} msg={msg} />
                    ))}
                    <div ref={messagesEndRef} />
                </div>
            </div>
            <ChatInput />
        </div>
    )
}

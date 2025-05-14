import { useValues } from 'kea'

import { chatListLogic, ChatMessage } from '../../scenes/chatListLogic'
import { ChatInput } from './ChatInput'

export function ChatWindow(): JSX.Element {
    const { selectedChatId, chats } = useValues(chatListLogic)

    return (
        <div className="bg-white h-full flex flex-col border border-gray-200 rounded relative pb-16">
            <div className="flex flex-col gap-2 h-full">
                {(chats.find((c) => c.id === selectedChatId)?.messages as ChatMessage[]).map((msg) => (
                    <div key={msg.id} className={`flex ${msg.sender === 'user' ? 'justify-start' : 'justify-end'}`}>
                        <div
                            className={`px-4 py-2 rounded max-w-xs break-words bg-gray-200'
                                ${msg.sender === 'user' ? ' text-left' : ' text-right'}
                            `}
                        >
                            {msg.content}
                        </div>
                    </div>
                ))}
            </div>
            <ChatInput />
        </div>
    )
}

import { useValues } from 'kea'

import { chatListLogic, ChatMessage } from '../../scenes/chatListLogic'
import { ChatInput } from './ChatInput'
import { Message } from './Message'

export function ChatWindow(): JSX.Element {
    const { selectedChatId, chats } = useValues(chatListLogic)

    return (
        <div className="bg-white h-full flex flex-col border border-gray-200 rounded relative pb-16">
            <div className="flex flex-col gap-2 h-full p-4">
                {(chats.find((c) => c.id === selectedChatId)?.messages as ChatMessage[]).map((msg) => (
                    <Message key={msg.id} msg={msg} />
                ))}
            </div>
            <ChatInput />
        </div>
    )
}

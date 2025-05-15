import { IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { chatListLogic, ChatMessage } from '../../scenes/chatListLogic'
import { ChatInput } from './ChatInput'
import { Message } from './Message'

export function ChatWindow(): JSX.Element {
    const { selectedChatId, chats } = useValues(chatListLogic)
    const { setSelectedChatId } = useActions(chatListLogic)
    return (
        <div className="bg-white h-full flex flex-col border border-gray-200 rounded relative pb-16">
            <div className="flex flex-col gap-2 h-full p-4">
                <div className="flex items-center justify-end border-b border-gray-200 pb-2 mb-2">
                    <LemonButton icon={<IconX />} size="xsmall" onClick={() => setSelectedChatId(null)} />
                </div>
                {(chats.find((c) => c.id === selectedChatId)?.messages as ChatMessage[]).map((msg) => (
                    <Message key={msg.id} msg={msg} />
                ))}
            </div>
            <ChatInput />
        </div>
    )
}

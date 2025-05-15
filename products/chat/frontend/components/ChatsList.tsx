import { useActions, useValues } from 'kea'

import { chatListLogic } from '../scenes/chatListLogic'
import { ChatListItem } from './ChatListItem'

export function ChatsList(): JSX.Element {
    const { selectedChatId, chats } = useValues(chatListLogic)
    const { setSelectedChatId } = useActions(chatListLogic)

    const displayableChats = chats.filter((chat) => chat.messages && chat.messages.length > 0)

    if (displayableChats.length === 0) {
        return <div className="flex flex-col items-center justify-center h-full">No chats with messages yet</div>
    }

    return (
        <aside className="overflow-y-auto h-full divide-y divide-gray-200 bg-white border border-gray-200 rounded">
            {displayableChats.map((chat) => (
                <ChatListItem
                    key={chat.id}
                    person={chat.person}
                    message={chat.messages.length ? chat.messages[chat.messages.length - 1].content : ''}
                    subject={chat.title ?? ''}
                    source_url={chat.source_url ?? ''}
                    isActive={selectedChatId === chat.id}
                    onClick={() => setSelectedChatId(chat.id ?? null)}
                    date={chat.messages.length ? chat.messages[chat.messages.length - 1].created_at : ''}
                    isUnread={!chat.messages.length || !chat.messages[chat.messages.length - 1].read}
                    isReply={chat.messages.length ? chat.messages[chat.messages.length - 1].is_assistant : false}
                />
            ))}
        </aside>
    )
}

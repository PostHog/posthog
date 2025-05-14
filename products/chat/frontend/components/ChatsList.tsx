import { useActions, useValues } from 'kea'

import { chatListLogic } from '../scenes/chatListLogic'
import { ChatListItem } from './ChatListItem'

export function ChatsList(): JSX.Element {
    const { selectedChatId, chats } = useValues(chatListLogic)
    const { setSelectedChatId } = useActions(chatListLogic)

    if (chats.length === 0) {
        return <div className="flex flex-col items-center justify-center h-full">No chats yet</div>
    }

    return (
        <aside className="overflow-y-auto h-full divide-y divide-gray-200 bg-white border border-gray-200 rounded">
            {chats.map((chat) => (
                <ChatListItem
                    key={chat.id}
                    user={chat.name}
                    message={chat.messages[chat.messages.length - 1].content}
                    isActive={selectedChatId === chat.id}
                    onClick={() => setSelectedChatId(chat.id)}
                    date={chat.messages[chat.messages.length - 1].dateCreated}
                    isUnread={chat.messages[chat.messages.length - 1].sender === 'assistant'}
                    isReply={chat.messages[chat.messages.length - 1].sender === 'user'}
                />
            ))}
        </aside>
    )
}

import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { chatListLogic, ChatMessage } from '../../scenes/chatListLogic'

export function ChatWindow(): JSX.Element {
    const { selectedChatId, chats, message } = useValues(chatListLogic)
    const { sendMessage, setMessage } = useActions(chatListLogic)

    return (
        <>
            <div className="flex flex-col gap-2">
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
            <div className="border-t border-gray-200 p-4">
                <div className="flex gap-2">
                    <LemonInput
                        type="text"
                        className="flex-1"
                        placeholder="Type a message…"
                        value={message}
                        onChange={(e) => setMessage(e)}
                    />
                    <LemonButton onClick={() => sendMessage(message)}>Send</LemonButton>
                </div>
            </div>
        </>
    )
}

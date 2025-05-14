import { ChatMessage } from '../../scenes/chatListLogic'

export function Message({ msg }: { msg: ChatMessage }): JSX.Element {
    return (
        <div key={msg.id} className={`flex ${msg.sender === 'user' ? 'justify-start' : 'justify-end'}`}>
            <div className="px-4 py-2 rounded-full max-w-xs break-words bg-gray-200">{msg.content}</div>
        </div>
    )
}

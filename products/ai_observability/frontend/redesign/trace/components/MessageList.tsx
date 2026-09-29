import { ThreadMessage } from '../types'
import { MessageBlock } from './MessageBlock'

export interface MessageListProps {
    messages: ThreadMessage[]
    emptyText: string
}

export function MessageList({ messages, emptyText }: MessageListProps): JSX.Element {
    if (messages.length === 0) {
        return <p className="m-0 text-sm text-secondary">{emptyText}</p>
    }
    return (
        <div className="flex flex-col gap-3">
            {messages.map((message) => (
                <MessageBlock key={message.id} message={message} />
            ))}
        </div>
    )
}

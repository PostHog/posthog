import { ThreadMessage } from '../types'
import { MessageBlock } from './MessageBlock'

export interface MessageListProps {
    messages: ThreadMessage[]
}

export function MessageList({ messages }: MessageListProps): JSX.Element {
    if (messages.length === 0) {
        return <p className="m-0 text-secondary">No messages were captured for this step.</p>
    }
    return (
        <div className="flex flex-col gap-2">
            {messages.map((message) => (
                <MessageBlock key={message.id} message={message} />
            ))}
        </div>
    )
}

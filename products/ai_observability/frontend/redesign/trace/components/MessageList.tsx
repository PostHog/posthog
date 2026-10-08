import { ThreadMessage } from '../types'
import { MessageBlock } from './MessageBlock'

export type MessageListDefaultOpen = 'all' | 'last'

export interface MessageListProps {
    messages: ThreadMessage[]
    emptyText: string
    defaultOpen: MessageListDefaultOpen
}

export function MessageList({ messages, emptyText, defaultOpen }: MessageListProps): JSX.Element {
    if (messages.length === 0) {
        return <p className="m-0 text-sm text-secondary">{emptyText}</p>
    }
    return (
        <div className="flex flex-col gap-3">
            {messages.map((message, index) => (
                <MessageBlock
                    key={message.id}
                    message={message}
                    defaultOpen={defaultOpen === 'all' || index === messages.length - 1}
                />
            ))}
        </div>
    )
}

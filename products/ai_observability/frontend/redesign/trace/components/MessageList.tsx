import { ThreadMessage } from '../types'
import { MessageBlock } from './MessageBlock'
import { messageContainsText } from './messageContainsText'

export type MessageListDefaultOpen = 'all' | 'last'

export interface MessageListProps {
    messages: ThreadMessage[]
    emptyText: string
    defaultOpen: MessageListDefaultOpen
    /** Messages that contain this text open too, so the search highlights in them show. */
    highlightQuery?: string | null
}

export function MessageList({
    messages,
    emptyText,
    defaultOpen,
    highlightQuery = null,
}: MessageListProps): JSX.Element {
    if (messages.length === 0) {
        return <p className="m-0 text-sm text-secondary">{emptyText}</p>
    }
    return (
        <div className="flex flex-col gap-3">
            {messages.map((message, index) => (
                <MessageBlock
                    key={message.id}
                    message={message}
                    defaultOpen={
                        defaultOpen === 'all' ||
                        index === messages.length - 1 ||
                        (!!highlightQuery && messageContainsText(message, highlightQuery))
                    }
                />
            ))}
        </div>
    )
}

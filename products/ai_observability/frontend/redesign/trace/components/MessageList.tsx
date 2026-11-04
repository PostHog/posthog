import { Fragment } from 'react'

import { IconArrowUp } from 'lib/lemon-ui/icons'
import { pluralize } from 'lib/utils/strings'

import { ThreadMessage } from '../types'
import { MessageBlock } from './MessageBlock'
import { messageContainsText } from './messageContainsText'

export interface MessageListProps {
    messages: ThreadMessage[]
    emptyText: string
    openFrom: number
    /** Messages that contain this text open too, so the search highlights in them show. */
    highlightQuery?: string | null
}

function earlierMessagesLabel(earlier: ThreadMessage[]): string {
    const turns = earlier.filter((message) => message.role === 'user').length
    return turns > 0
        ? `${pluralize(turns, 'earlier turn')} · ${pluralize(earlier.length, 'message')}`
        : pluralize(earlier.length, 'earlier message')
}

function EarlierMessagesDivider({ earlier }: { earlier: ThreadMessage[] }): JSX.Element {
    return (
        <div data-earlier-messages role="separator" className="flex items-center gap-1.5 text-xs text-secondary">
            <IconArrowUp className="shrink-0" />
            <span className="shrink-0">{earlierMessagesLabel(earlier)}</span>
            <span className="flex-1 border-t border-primary" />
        </div>
    )
}

export function MessageList({ messages, emptyText, openFrom, highlightQuery = null }: MessageListProps): JSX.Element {
    if (messages.length === 0) {
        return <p className="m-0 text-sm text-secondary">{emptyText}</p>
    }
    return (
        <div className="flex flex-col gap-3">
            {messages.map((message, index) => (
                <Fragment key={message.id}>
                    {index === openFrom && index > 0 ? (
                        <EarlierMessagesDivider earlier={messages.slice(0, openFrom)} />
                    ) : null}
                    <MessageBlock
                        message={message}
                        defaultOpen={
                            index >= openFrom || (!!highlightQuery && messageContainsText(message, highlightQuery))
                        }
                    />
                </Fragment>
            ))}
        </div>
    )
}

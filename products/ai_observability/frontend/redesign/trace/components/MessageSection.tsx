import { ThreadMessage } from '../types'
import { MessageList } from './MessageList'

export interface MessageSectionProps {
    title: string
    messages: ThreadMessage[]
    emptyText: string
    openFrom: number
    highlightQuery?: string | null
}

export function MessageSection({
    title,
    messages,
    emptyText,
    openFrom,
    highlightQuery = null,
}: MessageSectionProps): JSX.Element {
    return (
        <section className="flex flex-col gap-1.5">
            <h4 className="m-0 text-xs font-semibold text-secondary">{title}</h4>
            <MessageList
                messages={messages}
                emptyText={emptyText}
                openFrom={openFrom}
                highlightQuery={highlightQuery}
            />
        </section>
    )
}

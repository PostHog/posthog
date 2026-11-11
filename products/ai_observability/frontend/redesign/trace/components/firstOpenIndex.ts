import { MessagesOpening, ThreadMessage } from '../types'

/** The index from which messages open, so everything after the last user message reads as one turn. */
export function firstOpenIndex(messages: ThreadMessage[], opening: MessagesOpening): number {
    if (opening === 'everything') {
        return 0
    }
    const lastUserIndex = messages.findLastIndex((message) => message.role === 'user')
    return Math.max(lastUserIndex, 0)
}

import { ThreadMessage } from '../types'

export function conversationalMessages(messages: ThreadMessage[]): ThreadMessage[] {
    return messages.filter((message) => message.role !== 'system')
}

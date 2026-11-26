import { ConversationTurn, NodeSideContent, ThreadMessage } from '../types'

export function conversationalMessages(messages: ThreadMessage[]): ThreadMessage[] {
    return messages.filter((message) => message.role !== 'system')
}

export function conversationalSideMessages(side: NodeSideContent): ThreadMessage[] {
    return side.kind === 'messages' ? conversationalMessages(side.messages) : []
}

export function sideHasContent(side: NodeSideContent, conversationOnly: boolean = false): boolean {
    if (side.kind === 'json') {
        return side.value !== null && side.value !== ''
    }
    return conversationalMessages(side.messages).some((message) => !conversationOnly || !message.isInternal)
}

/** Internal messages count as content only while their toggle shows, which "conversation only" hides. */
export function turnHasContent(turn: ConversationTurn, conversationOnly: boolean = false): boolean {
    return sideHasContent(turn.input, conversationOnly) || sideHasContent(turn.output, conversationOnly)
}

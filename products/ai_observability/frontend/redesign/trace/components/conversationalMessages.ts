import { ConversationTurn, NodeSideContent, ThreadMessage } from '../types'

export function conversationalMessages(messages: ThreadMessage[]): ThreadMessage[] {
    return messages.filter((message) => message.role !== 'system')
}

export function conversationalSideMessages(side: NodeSideContent): ThreadMessage[] {
    return side.kind === 'messages' ? conversationalMessages(side.messages) : []
}

function sideHasContent(side: NodeSideContent): boolean {
    if (side.kind === 'json') {
        return side.value !== null && side.value !== ''
    }
    return conversationalMessages(side.messages).length > 0
}

export function turnHasContent(turn: ConversationTurn): boolean {
    return sideHasContent(turn.input) || sideHasContent(turn.output)
}

import { ConversationState, NodeLoad, ThreadMessage } from '../types'
import { readNodeIO } from './nodeIO'
import { TeamId } from './toAttachment'
import { toThreadMessages } from './toThreadMessages'

export interface MessageIO {
    input: ThreadMessage[]
    output: ThreadMessage[]
}

export function toMessageIO(io: { input: unknown; output: unknown }, sourceNodeId: string, teamId: TeamId): MessageIO {
    return {
        input: toThreadMessages(io.input, {
            defaultRole: 'user',
            idPrefix: `${sourceNodeId}-in`,
            sourceNodeId,
            teamId,
        }),
        output: toThreadMessages(io.output, {
            defaultRole: 'assistant',
            idPrefix: `${sourceNodeId}-out`,
            sourceNodeId,
            teamId,
        }),
    }
}

const THREAD_LOAD_ERROR = 'The conversation could not be loaded. Reload the page to try again.'

interface ThreadArgs {
    traceId: string
    createdAt: string
    load: NodeLoad | null
    teamId: TeamId
}

function readyThread(
    traceId: string,
    createdAt: string,
    messages: ThreadMessage[],
    error: string | null
): ConversationState {
    return { status: 'ready', turns: [{ id: traceId, timestamp: createdAt, messages, error }], activeTurnId: traceId }
}

export function toThread({ traceId, createdAt, load, teamId }: ThreadArgs): ConversationState {
    if (load === null) {
        return readyThread(traceId, createdAt, [], null)
    }
    switch (load.status) {
        case 'loading':
            return { status: 'loading' }
        case 'error':
            return { status: 'error', message: THREAD_LOAD_ERROR }
        case 'ready': {
            const { input, output } = toMessageIO(readNodeIO(load.node), load.node.id, teamId)
            return readyThread(traceId, createdAt, [...input, ...output], load.node.error)
        }
    }
}

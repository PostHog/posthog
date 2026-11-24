import { ConversationState, NodeLoad, NodeSideContent } from './types'

const THREAD_LOAD_ERROR = 'The conversation could not be loaded. Reload the page to try again.'

const EMPTY_SIDE: NodeSideContent = { kind: 'messages', messages: [] }

interface ThreadArgs {
    traceId: string
    createdAt: string
    load: NodeLoad | null
}

function readyThread(
    traceId: string,
    createdAt: string,
    input: NodeSideContent,
    output: NodeSideContent,
    error: string | null
): ConversationState {
    return {
        status: 'ready',
        turns: [{ id: traceId, timestamp: createdAt, input, output, error }],
        activeTurnId: traceId,
    }
}

export function toThread({ traceId, createdAt, load }: ThreadArgs): ConversationState {
    if (load === null) {
        return readyThread(traceId, createdAt, EMPTY_SIDE, EMPTY_SIDE, null)
    }
    switch (load.status) {
        case 'loading':
            return { status: 'loading' }
        case 'error':
            return { status: 'error', message: THREAD_LOAD_ERROR }
        case 'ready': {
            const { input, output } = load.node.content
            return readyThread(traceId, createdAt, input, output, load.node.error)
        }
    }
}

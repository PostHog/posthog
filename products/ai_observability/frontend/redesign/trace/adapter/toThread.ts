import { ConversationState, NodeLoad, ThreadMessage } from '../types'

const THREAD_LOAD_ERROR = 'The conversation could not be loaded. Reload the page to try again.'

interface ThreadArgs {
    traceId: string
    createdAt: string
    load: NodeLoad | null
}

function readyThread(
    traceId: string,
    createdAt: string,
    messages: ThreadMessage[],
    error: string | null
): ConversationState {
    return { status: 'ready', turns: [{ id: traceId, timestamp: createdAt, messages, error }], activeTurnId: traceId }
}

export function toThread({ traceId, createdAt, load }: ThreadArgs): ConversationState {
    if (load === null) {
        return readyThread(traceId, createdAt, [], null)
    }
    switch (load.status) {
        case 'loading':
            return { status: 'loading' }
        case 'error':
            return { status: 'error', message: THREAD_LOAD_ERROR }
        case 'ready': {
            const { input, output } = load.node.content
            const messages = [input, output].flatMap((side) => (side.kind === 'messages' ? side.messages : []))
            return readyThread(traceId, createdAt, messages, load.node.error)
        }
    }
}

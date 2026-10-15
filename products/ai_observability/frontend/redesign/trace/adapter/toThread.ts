import { LLMTrace } from '~/queries/schema/schema-general'

import { AIData } from '../../../aiObservabilityAIDataLogic'
import { pickUserVisibleTurn } from '../../../extractSessionTurns'
import { ConversationState, ThreadMessage } from '../types'
import { resolveEventIO } from './eventIO'
import { TeamId } from './toAttachment'
import { toThreadMessages } from './toThreadMessages'
import { eventError } from './toTraceTree'

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

function readyThread(trace: LLMTrace, messages: ThreadMessage[], error: string | null): ConversationState {
    return {
        status: 'ready',
        turns: [{ id: trace.id, timestamp: trace.createdAt, messages, error }],
        activeTurnId: trace.id,
    }
}

export function toThread(trace: LLMTrace, cache: Record<string, AIData | null>, teamId: TeamId): ConversationState {
    const turnEvent = pickUserVisibleTurn(trace)
    if (!turnEvent) {
        return readyThread(trace, [], null)
    }
    const io = resolveEventIO(turnEvent, cache)
    if (io.loading) {
        return { status: 'loading' }
    }
    const { input, output } = toMessageIO(io, turnEvent.id, teamId)
    return readyThread(trace, [...input, ...output], eventError(turnEvent))
}

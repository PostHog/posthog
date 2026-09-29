import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { AIData } from '../../../aiObservabilityAIDataLogic'
import { pickUserVisibleTurn } from '../../../extractSessionTurns'
import { ConversationTurn, ThreadMessage } from '../types'
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

function turnMessages(event: LLMTraceEvent, cache: Record<string, AIData | null>, teamId: TeamId): ThreadMessage[] {
    const { input, output } = toMessageIO(resolveEventIO(event, cache), event.id, teamId)
    return [...input, ...output]
}

export function toThread(
    trace: LLMTrace,
    cache: Record<string, AIData | null>,
    teamId: TeamId
): { turns: ConversationTurn[]; activeTurnId: string } {
    const turnEvent = pickUserVisibleTurn(trace)
    const turn: ConversationTurn = {
        id: trace.id,
        timestamp: trace.createdAt,
        messages: turnEvent ? turnMessages(turnEvent, cache, teamId) : [],
        error: turnEvent ? eventError(turnEvent) : null,
    }
    return { turns: [turn], activeTurnId: trace.id }
}

import { LLMTraceEvent } from '~/queries/schema/schema-general'

import { AIData, AIDataLookup } from '../../../aiObservabilityAIDataLogic'
import { getLLMEventKind, readAiInput, readAiOutput } from '../../../utils'

function generationOutput(event: LLMTraceEvent): unknown {
    return event.properties.$ai_output_choices ?? event.properties.$ai_output
}

function isMissingGenerationData(event: LLMTraceEvent): boolean {
    return event.properties.$ai_input == null || generationOutput(event) == null
}

export function heavyDataLookup(event: LLMTraceEvent, traceId: string): AIDataLookup | null {
    if (getLLMEventKind(event) !== 'generation' || !isMissingGenerationData(event)) {
        return null
    }
    return {
        eventId: event.id,
        input: event.properties.$ai_input,
        output: generationOutput(event),
        tools: event.properties.$ai_tools,
        traceId,
        timestamp: event.createdAt,
    }
}

export function resolveEventIO(
    event: LLMTraceEvent,
    cache: Record<string, AIData | null>
): { input: unknown; output: unknown; loading: boolean } {
    const kind = getLLMEventKind(event)
    if (kind === 'generation') {
        const cached = cache[event.id]
        const input = cached?.input ?? event.properties.$ai_input
        const output = cached?.output ?? generationOutput(event)
        return { input, output, loading: isMissingGenerationData(event) && cached === undefined }
    }
    if (kind === 'embedding') {
        return { input: event.properties.$ai_input, output: null, loading: false }
    }
    return { input: readAiInput(event.properties), output: readAiOutput(event.properties), loading: false }
}

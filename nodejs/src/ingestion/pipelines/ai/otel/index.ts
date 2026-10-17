import { parseJSON } from '~/common/utils/json-parse'
import { aiOtelEventTypeCounter, aiOtelMiddlewareCounter } from '~/ingestion/pipelines/ai/metrics'
import { PluginEvent } from '~/plugin-scaffold'

import { mapOtelAttributes } from './attribute-mapping'
import { anthropic } from './middleware/anthropic'
import { pydanticAi } from './middleware/pydantic-ai'
import { traceloop } from './middleware/traceloop'
import { OtelLibraryMiddleware } from './middleware/types'
import { vercelAi } from './middleware/vercel-ai'

// Middleware registry — checked in order, first match wins.
const MIDDLEWARES: OtelLibraryMiddleware[] = [pydanticAi, traceloop, vercelAi, anthropic]

// Runs after the middlewares, because each of them can resolve a session id the producer set on
// purpose. The conversation id stays on the event: where a producer has a wider session grouping,
// it still separates the threads.
function setSessionIdFromConversationId(event: PluginEvent): void {
    const props = event.properties
    const conversationId = props?.['gen_ai.conversation.id']
    if (props && props['$ai_session_id'] === undefined && typeof conversationId === 'string' && conversationId !== '') {
        props['$ai_session_id'] = conversationId
    }
}

const TOOL_CALL_STATE_KEYS: Record<string, string> = {
    'gen_ai.tool.call.arguments': '$ai_input_state',
    'gen_ai.tool.call.result': '$ai_output_state',
}

// Tool call spans with only standard gen_ai.* attributes, as Vercel AI SDK 7 sends them, match no
// middleware. Runs before the generic mapping, which strips gen_ai.operation.name.
function setToolCallState(event: PluginEvent): void {
    const props = event.properties
    if (!props || props['gen_ai.operation.name'] !== 'execute_tool') {
        return
    }
    for (const [otelKey, phKey] of Object.entries(TOOL_CALL_STATE_KEYS)) {
        if (props[otelKey] !== undefined && props[phKey] === undefined) {
            props[phKey] = parseToolCallValue(props[otelKey])
            delete props[otelKey]
        }
    }
}

// Same ceiling as MAX_OLDER_SPEC_EVENTS_LENGTH in attribute-mapping.ts. It bounds what one value
// can make the worker allocate.
const MAX_TOOL_CALL_VALUE_LENGTH = 500_000

function parseToolCallValue(value: unknown): unknown {
    // A longer string stays as text.
    if (typeof value !== 'string' || value.length > MAX_TOOL_CALL_VALUE_LENGTH) {
        return value
    }
    let parsed: unknown
    try {
        parsed = parseJSON(value)
    } catch {
        return value
    }
    // The conversation view shows nothing for a bare number, boolean or null, so keep those as text.
    if (typeof parsed === 'number' || typeof parsed === 'boolean' || parsed === null) {
        return value
    }
    return parsed
}

export function convertOtelEvent(event: PluginEvent): void {
    const middleware = MIDDLEWARES.find((mw) => mw.matches(event))
    const library = middleware?.name ?? 'none'

    if (middleware) {
        middleware.process(event, () => mapOtelAttributes(event))
    } else {
        setToolCallState(event)
        mapOtelAttributes(event)
    }

    setSessionIdFromConversationId(event)

    aiOtelMiddlewareCounter.labels({ library }).inc()
    aiOtelEventTypeCounter.labels({ event_type: event.event, library }).inc()
}

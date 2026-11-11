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

export function convertOtelEvent(event: PluginEvent): void {
    const middleware = MIDDLEWARES.find((mw) => mw.matches(event))
    const library = middleware?.name ?? 'none'

    if (middleware) {
        middleware.process(event, () => mapOtelAttributes(event))
    } else {
        mapOtelAttributes(event)
    }

    setSessionIdFromConversationId(event)

    aiOtelMiddlewareCounter.labels({ library }).inc()
    aiOtelEventTypeCounter.labels({ event_type: event.event, library }).inc()
}

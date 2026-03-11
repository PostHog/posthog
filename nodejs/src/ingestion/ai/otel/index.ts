import { PluginEvent } from '~/plugin-scaffold'

import { aiOtelEventTypeCounter, aiOtelMiddlewareCounter } from '../metrics'
import { mapOtelAttributes } from './attribute-mapping'
import { pydanticAi } from './middleware/pydantic-ai'
import { OtelLibraryMiddleware } from './middleware/types'
import { vercelAi } from './middleware/vercel-ai'

// Middleware registry — checked in order, first match wins.
const MIDDLEWARES: OtelLibraryMiddleware[] = [pydanticAi, vercelAi]

export function convertOtelEvent(event: PluginEvent): void {
    const middleware = MIDDLEWARES.find((mw) => mw.matches(event))
    const library = middleware?.name ?? 'none'

    if (middleware) {
        middleware.process(event, () => mapOtelAttributes(event))
    } else {
        mapOtelAttributes(event)
    }

    aiOtelMiddlewareCounter.labels({ library }).inc()
    aiOtelEventTypeCounter.labels({ event_type: event.event, library }).inc()
}

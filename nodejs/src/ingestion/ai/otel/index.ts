import { PluginEvent } from '~/plugin-scaffold'

import { mapOtelAttributes } from './attribute-mapping'
import { pydanticAi } from './middleware/pydantic-ai'
import { OtelLibraryMiddleware } from './middleware/types'
import { vercelAi } from './middleware/vercel-ai'

// Middleware registry — checked in order, first match wins.
const MIDDLEWARES: OtelLibraryMiddleware[] = [pydanticAi, vercelAi]

function detectMiddleware(event: PluginEvent): OtelLibraryMiddleware | undefined {
    for (const mw of MIDDLEWARES) {
        if (mw.markerKeys.some((key) => event.properties?.[key] !== undefined)) {
            return mw
        }
    }
    return undefined
}

export function convertOtelEvent(event: PluginEvent): void {
    const middleware = detectMiddleware(event)

    if (middleware) {
        middleware.process(event, () => mapOtelAttributes(event))
    } else {
        mapOtelAttributes(event)
    }
}

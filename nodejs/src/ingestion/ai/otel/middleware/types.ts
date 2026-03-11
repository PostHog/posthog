import { PluginEvent } from '~/plugin-scaffold'

export interface OtelLibraryMiddleware {
    /** Unique identifier used in $ai_lib, e.g. 'opentelemetry/pydantic-ai' */
    name: string

    /** Attribute keys whose presence indicates this library produced the span. */
    markerKeys: string[]

    /** Transform library-specific attributes into PostHog's standard AI properties. */
    process: (event: PluginEvent, next: () => void) => void
}

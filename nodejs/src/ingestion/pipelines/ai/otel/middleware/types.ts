import { PluginEvent } from '~/plugin-scaffold'

export interface OtelLibraryMiddleware {
    /** Stable identifier used for metrics labels (e.g. 'pydantic-ai', 'vercel-ai'). */
    name: string

    /** Whether this middleware should handle the given event. */
    matches: (event: PluginEvent) => boolean

    /** Transform library-specific attributes into PostHog's standard AI properties. */
    process: (event: PluginEvent, next: () => void) => void
}

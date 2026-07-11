import { LiveEvent } from '~/types'

/** Prepend new events to existing state, deduplicating by uuid and capping at `limit`. */
export function deduplicateEvents(state: LiveEvent[], incoming: LiveEvent[], limit: number): LiveEvent[] {
    const seen = new Set(state.map((e) => e.uuid).filter(Boolean))
    const newEvents: LiveEvent[] = []

    for (const event of incoming) {
        if (!seen.has(event.uuid)) {
            newEvents.push(event)
            seen.add(event.uuid)
        }
    }

    // duplicate-only batches keep the existing array identity so downstream memoization holds
    if (newEvents.length === 0) {
        return state.length > limit ? state.slice(0, limit) : state
    }

    return [...newEvents, ...state].slice(0, limit)
}

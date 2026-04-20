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

    return [...newEvents, ...state].slice(0, limit)
}

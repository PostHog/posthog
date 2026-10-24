import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import type { EventType } from '~/types'

export type EventCategory = 'posthog' | 'custom' | 'snapshot'

export function classifyEvent(e: EventType): EventCategory {
    if (e.event === '$snapshot') {
        return 'snapshot'
    }
    if (e.event.startsWith('$') || Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP.events).includes(e.event)) {
        return 'posthog'
    }
    return 'custom'
}

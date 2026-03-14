import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'

import { uuid } from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { CLOUD_INTERNAL_POSTHOG_PROPERTY_KEYS } from '~/taxonomy/taxonomy'
import { CORE_FILTER_DEFINITIONS_BY_GROUP, PROPERTY_KEYS } from '~/taxonomy/taxonomy'
import { toolbarConfigLogic } from '~/toolbar/core/toolbarConfigLogic'
import { EventType } from '~/types'

import type { eventDebugMenuLogicType } from './eventDebugMenuLogicType'

function tryRegexMatch(text: string, pattern: string): boolean {
    // If the pattern looks like /regex/ or /regex/flags, treat as regex
    const regexMatch = pattern.match(/^\/(.+)\/([gimsuy]*)$/)
    if (regexMatch) {
        try {
            const re = new RegExp(regexMatch[1], regexMatch[2])
            return re.test(text)
        } catch {
            // Invalid regex, fall back to plain includes
            return text.toLowerCase().includes(pattern.toLowerCase())
        }
    }
    // Plain case-insensitive substring match
    return text.toLowerCase().includes(pattern.toLowerCase())
}

const MAX_EVENTS = 5000

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

export const eventDebugMenuLogic = kea<eventDebugMenuLogicType>([
    path(['toolbar', 'debug', 'eventDebugMenuLogic']),
    connect(() => ({
        values: [toolbarConfigLogic, ['posthog']],
    })),
    actions({
        addEvent: (event: EventType) => ({ event }),
        markExpanded: (id: string | null | undefined) => ({ id }),
        setSearchText: (searchText: string) => ({ searchText }),
        setSelectedEventType: (eventType: EventCategory, enabled: boolean) => ({
            eventType,
            enabled,
        }),
        setHidePostHogProperties: (hide: boolean) => ({ hide }),
        setHidePostHogFlags: (hide: boolean) => ({ hide }),
        togglePinnedEvent: (eventId: string) => ({ eventId }),
        toggleRelativeTimestamps: true,
        togglePaused: true,
        clearEvents: true,
        exportEvents: true,
    }),
    reducers({
        hidePostHogProperties: [
            false,
            {
                setHidePostHogProperties: (_, { hide }) => hide,
            },
        ],
        hidePostHogFlags: [
            false,
            {
                setHidePostHogFlags: (_, { hide }) => hide,
            },
        ],
        relativeTimestamps: [
            false,
            {
                toggleRelativeTimestamps: (state) => !state,
            },
        ],
        searchText: [
            '',
            {
                setSearchText: (_, { searchText }) => searchText,
            },
        ],
        selectedEventTypes: [
            ['posthog', 'custom'] as EventCategory[],
            {
                setSelectedEventType: (state, { eventType, enabled }) => {
                    if (enabled) {
                        return state.includes(eventType) ? state : [...state, eventType]
                    }
                    return state.filter((t) => t !== eventType)
                },
            },
        ],

        events: [
            [] as EventType[],
            {
                addEvent: (state, { event }) => {
                    const next = [{ ...event, uuid: event.uuid || uuid() }, ...state]
                    return next.length > MAX_EVENTS ? next.slice(0, MAX_EVENTS) : next
                },
                clearEvents: () => [],
            },
        ],
        // Events buffered while paused, prepended on resume
        bufferedEvents: [
            [] as EventType[],
            {
                addEvent: (state, { event }) => {
                    const next = [{ ...event, uuid: event.uuid || uuid() }, ...state]
                    return next.length > MAX_EVENTS ? next.slice(0, MAX_EVENTS) : next
                },
                togglePaused: () => [],
                clearEvents: () => [],
            },
        ],
        isPaused: [
            false,
            {
                togglePaused: (state) => !state,
            },
        ],
        expandedEvent: [
            null as string | null | undefined,
            {
                markExpanded: (_, { id }) => id,
            },
        ],
        pinnedEventIds: [
            new Set<string>(),
            {
                togglePinnedEvent: (state, { eventId }) => {
                    const next = new Set(state)
                    if (next.has(eventId)) {
                        next.delete(eventId)
                    } else {
                        next.add(eventId)
                    }
                    return next
                },
                clearEvents: () => new Set<string>(),
            },
        ],
    }),
    selectors({
        isCollapsedEventRow: [
            (s) => [s.expandedEvent],
            (expandedEvent) => {
                return (eventId: string | null | undefined): boolean => {
                    return eventId !== expandedEvent
                }
            },
        ],
        // When paused, show a frozen snapshot; when live, show all events
        visibleEvents: [
            (s) => [s.events, s.bufferedEvents, s.isPaused],
            (events, bufferedEvents, isPaused): EventType[] => {
                if (isPaused) {
                    // Show events minus anything buffered since pause
                    return events.slice(bufferedEvents.length)
                }
                return events
            },
        ],
        searchFilteredEvents: [
            (s) => [s.visibleEvents, s.searchText],
            (visibleEvents, searchText) => {
                return visibleEvents.filter((e: EventType) => {
                    if (searchText && !tryRegexMatch(e.event, searchText)) {
                        return false
                    }
                    return true
                })
            },
        ],
        searchFilteredEventsCount: [
            (s) => [s.searchFilteredEvents],
            (searchFilteredEvents): Record<EventCategory, number> => {
                const counts: Record<EventCategory, number> = { posthog: 0, custom: 0, snapshot: 0 }
                searchFilteredEvents.forEach((e: EventType) => {
                    counts[classifyEvent(e)] += 1
                })
                return counts
            },
        ],

        activeFilteredEvents: [
            (s) => [s.selectedEventTypes, s.searchFilteredEvents],
            (selectedEventTypes, searchFilteredEvents) => {
                return searchFilteredEvents.filter((e: EventType) => {
                    return selectedEventTypes.includes(classifyEvent(e))
                })
            },
        ],

        totalEventsCount: [(s) => [s.visibleEvents], (visibleEvents): number => visibleEvents.length],

        bufferedCount: [(s) => [s.bufferedEvents], (bufferedEvents): number => bufferedEvents.length],

        pinnedEvents: [
            (s) => [s.activeFilteredEvents, s.pinnedEventIds],
            (activeFilteredEvents, pinnedEventIds): EventType[] => {
                if (pinnedEventIds.size === 0) {
                    return []
                }
                return activeFilteredEvents.filter((e: EventType) => e.uuid && pinnedEventIds.has(e.uuid))
            },
        ],

        unpinnedEvents: [
            (s) => [s.activeFilteredEvents, s.pinnedEventIds],
            (activeFilteredEvents, pinnedEventIds): EventType[] => {
                if (pinnedEventIds.size === 0) {
                    return activeFilteredEvents
                }
                return activeFilteredEvents.filter((e: EventType) => !e.uuid || !pinnedEventIds.has(e.uuid))
            },
        ],

        expandedProperties: [
            (s) => [s.expandedEvent, s.events, s.hidePostHogProperties, s.hidePostHogFlags],
            (expandedEvent, events, hidePostHogProperties, hidePostHogFlags) => {
                if (!expandedEvent) {
                    return []
                }
                const allProperties = events.find((e) => e.uuid === expandedEvent)?.properties
                if (!allProperties) {
                    return []
                }

                const posthogPropertiesFiltered = hidePostHogProperties
                    ? Object.fromEntries(
                          Object.entries(allProperties).filter(([key]) => {
                              const isPostHogProperty = key.startsWith('$') && PROPERTY_KEYS.includes(key)
                              const isNonDollarPostHogProperty = CLOUD_INTERNAL_POSTHOG_PROPERTY_KEYS.includes(key)
                              return !isPostHogProperty && !isNonDollarPostHogProperty
                          })
                      )
                    : allProperties

                const posthogFlagsFiltered = hidePostHogFlags
                    ? Object.fromEntries(
                          Object.entries(posthogPropertiesFiltered).filter(([key]) => {
                              if (key === '$active_feature_flags') {
                                  return false
                              } else if (key.startsWith('$feature/')) {
                                  return false
                              }

                              return true
                          })
                      )
                    : posthogPropertiesFiltered

                return posthogFlagsFiltered
            },
        ],

        exportableEvents: [
            (s) => [s.activeFilteredEvents],
            (activeFilteredEvents): object[] => {
                return activeFilteredEvents.map((e: EventType) => ({
                    event: e.event,
                    timestamp: e.timestamp,
                    properties: e.properties,
                    uuid: e.uuid,
                }))
            },
        ],
    }),
    afterMount(({ values, actions, cache }) => {
        cache.disposables.add(() => {
            return values.posthog?.on('eventCaptured', (e) => {
                actions.addEvent(e)
            })
        }, 'posthogEventListener')
    }),
    permanentlyMount(),
])

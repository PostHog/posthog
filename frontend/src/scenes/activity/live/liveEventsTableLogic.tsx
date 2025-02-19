import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { teamLogic } from 'scenes/teamLogic'

import type { LiveEvent } from '~/types'

import type { liveEventsTableLogicType } from './liveEventsTableLogicType'

export const liveEventsTableLogic = kea<liveEventsTableLogicType>([
    path(['scenes', 'activity', 'live-events', 'liveEventsTableLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    actions(() => ({
        addEvents: (events) => ({ events }),
        clearEvents: true
    })),
    reducers({
        events: [
            [] as LiveEvent[],
            {
                addEvents: (state, { events }) => {
                    const newState = [...events, ...state]
                    if (newState.length > 500) {
                        return newState.slice(0, 400)
                    }
                    return newState
                },
                clearEvents: () => [],
            },
        ],
    }),
    selectors(({ selectors }) => ({
        eventCount: [() => [selectors.events], (events: any) => events.length],
    })),
    listeners(({ actions }) => ({
        setFilters: () => {
            actions.clearEvents()
            actions.updateEventsConnection()
        },
        addEvents: ({ events }) => {
            if (events.length > 0) {
                const event = events[0]
                const eventUrl = event.properties?.$current_url
                if (eventUrl) {
                    const eventHost = new URL(eventUrl).host
                    const eventProtocol = new URL(eventUrl).protocol
                    actions.addEventHost(`${eventProtocol}//${eventHost}`)
                }
            }
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.updateEventsConnection()
            cache.statsInterval = setInterval(() => {
                actions.pollStats()
            }, 1500)
        },
        beforeUnmount: () => {
            if (cache.eventSourceController) {
                cache.eventSourceController.abort()
            }
            if (cache.statsInterval) {
                clearInterval(cache.statsInterval)
            }
        },
    })),
])

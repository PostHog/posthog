import { kea } from 'kea'

// Import the necessary type

export const liveEventsTableLogic = kea({
    path: ['scenes', 'events-management', 'live-events', 'liveEventsTableLogic'],

    actions: () => ({
        addEvents: (events) => ({ events }),
        clearEvents: true,
        setFilters: (filters) => ({ filters }),
        updateSSESource: (source) => ({ source }),
        updateSSEConnection: true,
        pauseStream: true,
        resumeStream: true,
        setCurEventProperties: (curEventProperties) => ({ curEventProperties }),
    }),

    reducers: () => ({
        events: [
            [],
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
        filters: [
            { teamId: 2, distinctId: '', eventType: '' },
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        sseSource: [
            null,
            {
                updateSSESource: (_, { source }) => source,
            },
        ],
        streamPaused: [
            false,
            {
                pauseStream: () => true,
                resumeStream: () => false,
            },
        ],
        curEventProperties: [
            [],
            {
                setCurEventProperties: (_, { curEventProperties }) => curEventProperties,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        eventCount: [() => [selectors.events], (events: any) => events.length],
    }),

    listeners: ({ actions, values }) => ({
        addEvents: () => {
            // Optionally handle side effects here
        },
        setFilters: () => {
            // Clear events when filters change
            actions.clearEvents()
            // Update the SSE connection with new filters
            actions.updateSSEConnection()
        },
        updateSSEConnection: async () => {
            if (values.sseSource) {
                values.sseSource.close()
            }

            if (values.streamPaused) {
                return
            }

            const { teamId, distinctId, eventType } = values.filters
            const url = new URL('http://live-events/events')
            if (teamId) {
                url.searchParams.append('teamId', teamId)
            }
            if (distinctId) {
                url.searchParams.append('distinctId', distinctId)
            }
            if (eventType) {
                url.searchParams.append('eventType', eventType)
            }

            const source = new EventSource(url.toString())

            const batch: Record<string, any>[] = []
            source.onmessage = function (event) {
                const eventData = JSON.parse(event.data) // Assuming the event data is in JSON format
                batch.push(eventData)
                if (batch.length >= 5) {
                    // Process in batches of 5
                    actions.addEvents(batch)
                    batch.length = 0
                }
            }

            source.onerror = function () {
                // Handle errors, possibly retrying connection
            }

            actions.updateSSESource(source)
        },
        pauseStream: () => {
            if (values.sseSource) {
                values.sseSource.close()
            }
        },
        resumeStream: () => {
            actions.updateSSEConnection()
        },
    }),

    events: ({ actions, values }) => ({
        afterMount: () => {
            actions.updateSSEConnection()
            return () => {
                if (values.sseSource) {
                    values.sseSource.close()
                }
            }
        },
    }),
})

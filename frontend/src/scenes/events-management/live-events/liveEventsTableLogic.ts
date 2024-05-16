import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { teamLogic } from 'scenes/teamLogic'

export const liveEventsTableLogic = kea([
    path(['scenes', 'events-management', 'live-events', 'liveEventsTableLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    actions(() => ({
        addEvents: (events) => ({ events }),
        clearEvents: true,
        setFilters: (filters) => ({ filters }),
        updateSSESource: (source) => ({ source }),
        updateSSEConnection: true,
        pauseStream: true,
        resumeStream: true,
        setCurEventProperties: (curEventProperties) => ({ curEventProperties }),
        setClientSideFilters: (clientSideFilters) => ({ clientSideFilters }),
    })),
    reducers({
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
            { teamId: getCurrentTeamId() },
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        clientSideFilters: [
            {},
            {
                setClientSideFilters: (_, { clientSideFilters }) => clientSideFilters,
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
    selectors(({ selectors }) => ({
        eventCount: [() => [selectors.events], (events: any) => events.length],
        filteredEvents: [
            (s) => [s.events, s.clientSideFilters],
            (events, clientSideFilters) => {
                return events.filter((event) => {
                    return Object.entries(clientSideFilters).every(([key, value]) => {
                        return event[key] === value
                    })
                })
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        setFilters: () => {
            actions.clearEvents()
            actions.updateSSEConnection()
        },
        updateSSEConnection: async () => {
            if (values.sseSource) {
                values.sseSource.close()
            }

            if (values.streamPaused) {
                return
            }

            if (!values.currentTeam) {
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

            const source = new window.EventSource(url.toString(), {
                headers: {
                    Authorization: `Bearer ${actions.currentTeam.jwt_token}`,
                },
            })

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
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            actions.updateSSEConnection()
            return () => {
                if (values.sseSource) {
                    values.sseSource.close()
                }
            }
        },
    })),
])

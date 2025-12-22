import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { SessionEventType } from '~/types'

import type { sessionProfileLogicType } from './sessionProfileLogicType'

export interface SessionProfileLogicProps {
    sessionId: string
}

export interface SessionData {
    session_id: string
    distinct_id: string
    person_properties: Record<string, any> | null
    start_timestamp: string
    end_timestamp: string
    entry_current_url: string | null
    end_current_url: string | null
    urls: string[]
    num_uniq_urls: number
    pageview_count: number
    autocapture_count: number
    screen_count: number
    session_duration: number
    channel_type: string | null
    is_bounce: boolean
    entry_hostname: string | null
    entry_pathname: string | null
    entry_utm_source: string | null
    entry_utm_campaign: string | null
    entry_utm_medium: string | null
    entry_referring_domain: string | null
    last_external_click_url: string | null
}

export const sessionProfileLogic = kea<sessionProfileLogicType>([
    path(['scenes', 'sessions', 'sessionProfileLogic']),
    props({} as SessionProfileLogicProps),
    key((props) => props.sessionId),
    actions({
        loadSessionData: true,
        loadSessionEvents: true,
        loadMoreSessionEvents: true,
        loadEventDetails: (eventId: string, eventName: string) => ({ eventId, eventName }),
        setHasMoreEvents: (hasMore: boolean) => ({ hasMore }),
        updateEventsOffset: (offset: number) => ({ offset }),
        loadTotalEventCount: true,
        setSortOrder: (sortOrder: 'asc' | 'desc') => ({ sortOrder }),
        loadRecordingAvailability: true,
        setEventsListFolded: (isFolded: boolean) => ({ isFolded }),
        loadSupportTicketEvents: true,
    }),
    reducers({
        hasMoreEvents: [
            true,
            {
                loadSessionEventsSuccess: (_, { sessionEvents }) => sessionEvents.length === 50,
                setHasMoreEvents: (_, { hasMore }) => hasMore,
            },
        ],
        eventsOffset: [
            0 as number,
            {
                loadSessionEventsSuccess: (_, { sessionEvents }) => sessionEvents.length,
                loadMoreSessionEvents: (state) => state, // Preserve before loading
                updateEventsOffset: (_, { offset }) => offset,
                setSortOrder: () => 0, // Reset offset when sort changes
            },
        ],
        sortOrder: [
            'asc' as 'asc' | 'desc',
            {
                setSortOrder: (_, { sortOrder }) => sortOrder,
            },
        ],
        eventsListFolded: [
            false,
            {
                setEventsListFolded: (_, { isFolded }) => isFolded,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        sessionData: [
            null as SessionData | null,
            {
                loadSessionData: async () => {
                    // First get the session data
                    const sessionQuery = hogql`
                        SELECT
                            session_id,
                            distinct_id,
                            $start_timestamp,
                            $end_timestamp,
                            $entry_current_url,
                            $end_current_url,
                            $urls,
                            $num_uniq_urls,
                            $pageview_count,
                            $autocapture_count,
                            $screen_count,
                            $session_duration,
                            $channel_type,
                            $is_bounce,
                            $entry_hostname,
                            $entry_pathname,
                            $entry_utm_source,
                            $entry_utm_campaign,
                            $entry_utm_medium,
                            $entry_referring_domain,
                            $last_external_click_url
                        FROM sessions
                        WHERE $start_timestamp >= UUIDv7ToDateTime(toUUID(${props.sessionId}))
                            AND $start_timestamp <= UUIDv7ToDateTime(toUUID(${props.sessionId})) + INTERVAL 1 HOUR
                            AND session_id = ${props.sessionId}
                        LIMIT 1
                    `

                    const tags = { scene: 'SessionProfile', productKey: 'persons' }
                    const response = await api.queryHogQL(sessionQuery, tags)
                    const row = response.results?.[0]

                    if (!row) {
                        return null
                    }

                    const distinct_id = row[1]

                    // Second query: get person properties if we have a distinct_id
                    let person_properties: Record<string, any> | null = null
                    if (distinct_id && distinct_id !== '$posthog_cookieless') {
                        try {
                            const personQuery = hogql`
                                SELECT properties
                                FROM persons
                                WHERE id IN (
                                    SELECT person_id
                                    FROM person_distinct_ids
                                    WHERE distinct_id = ${distinct_id}
                                    LIMIT 1
                                )
                                LIMIT 1
                            `
                            const personResponse = await api.queryHogQL(personQuery, tags)
                            const personRow = personResponse.results?.[0]
                            if (personRow && personRow[0]) {
                                person_properties = JSON.parse(personRow[0])
                            }
                        } catch (e) {
                            console.error('Failed to fetch person properties:', e)
                        }
                    }

                    return {
                        session_id: row[0],
                        distinct_id: row[1],
                        start_timestamp: row[2],
                        end_timestamp: row[3],
                        entry_current_url: row[4],
                        end_current_url: row[5],
                        urls: row[6] || [],
                        num_uniq_urls: row[7] || 0,
                        pageview_count: row[8] || 0,
                        autocapture_count: row[9] || 0,
                        screen_count: row[10] || 0,
                        session_duration: row[11] || 0,
                        channel_type: row[12],
                        is_bounce: row[13] || false,
                        entry_hostname: row[14],
                        entry_pathname: row[15],
                        entry_utm_source: row[16],
                        entry_utm_campaign: row[17],
                        entry_utm_medium: row[18],
                        entry_referring_domain: row[19],
                        last_external_click_url: row[20],
                        person_properties,
                    }
                },
            },
        ],
        sessionEvents: [
            null as SessionEventType[] | null,
            {
                loadSessionEvents: async () => {
                    const sortOrder = values.sortOrder || 'asc'
                    const eventsQuery =
                        sortOrder === 'asc'
                            ? hogql`
                        SELECT
                            uuid,
                            event,
                            timestamp,
                            properties.$window_id,
                            properties.$current_url,
                            properties.$event_type,
                            properties.$screen_name,
                            properties.$pathname,
                            properties.$exception_type,
                            properties.$exception_message,
                            properties.$console_log_level,
                            properties.$response_status,
                            properties.$exception_list,
                            distinct_id
                        FROM events
                        WHERE timestamp >= UUIDv7ToDateTime(toUUID(${props.sessionId}))
                            AND timestamp <= UUIDv7ToDateTime(toUUID(${props.sessionId})) + INTERVAL 2 DAY
                            AND \`$session_id\` = ${props.sessionId}
                        ORDER BY timestamp ASC
                        LIMIT 50
                    `
                            : hogql`
                        SELECT
                            uuid,
                            event,
                            timestamp,
                            properties.$window_id,
                            properties.$current_url,
                            properties.$event_type,
                            properties.$screen_name,
                            properties.$pathname,
                            properties.$exception_type,
                            properties.$exception_message,
                            properties.$console_log_level,
                            properties.$response_status,
                            properties.$exception_list,
                            distinct_id
                        FROM events
                        WHERE timestamp >= UUIDv7ToDateTime(toUUID(${props.sessionId}))
                            AND timestamp <= UUIDv7ToDateTime(toUUID(${props.sessionId})) + INTERVAL 2 DAY
                            AND \`$session_id\` = ${props.sessionId}
                        ORDER BY timestamp DESC
                        LIMIT 50
                    `

                    const response = await api.queryHogQL(eventsQuery, {
                        scene: 'SessionProfile',
                        productKey: 'persons',
                    })

                    return (response.results || []).map((row: any): SessionEventType => {
                        const properties: Record<string, any> = {}

                        // Only add properties if they have values (not null/undefined)
                        if (row[3] != null) {
                            properties.$window_id = row[3]
                        }
                        if (row[4] != null) {
                            properties.$current_url = row[4]
                        }
                        if (row[5] != null) {
                            properties.$event_type = row[5]
                        }
                        if (row[6] != null) {
                            properties.$screen_name = row[6]
                        }
                        if (row[7] != null) {
                            properties.$pathname = row[7]
                        }
                        if (row[8] != null) {
                            properties.$exception_type = row[8]
                        }
                        if (row[9] != null) {
                            properties.$exception_message = row[9]
                        }
                        if (row[10] != null) {
                            properties.$console_log_level = row[10]
                        }
                        if (row[11] != null) {
                            properties.$response_status = row[11]
                        }

                        // Parse $exception_list if it exists (comes as JSON string)
                        if (row[12] != null) {
                            try {
                                properties.$exception_list = JSON.parse(row[12])
                            } catch (e) {
                                console.error(e)
                                properties.$exception_list = []
                            }
                        }

                        return {
                            id: row[0],
                            event: row[1],
                            timestamp: row[2],
                            properties,
                            distinct_id: row[13],
                            fullyLoaded: false,
                        }
                    })
                },
                loadMoreSessionEvents: async (_, breakpoint) => {
                    await breakpoint(500) // Debounce rapid scroll

                    const currentEvents = values.sessionEvents || []
                    const offset = values.eventsOffset
                    const sortOrder = values.sortOrder || 'asc'

                    const eventsQuery =
                        sortOrder === 'asc'
                            ? hogql`
                        SELECT
                            uuid,
                            event,
                            timestamp,
                            properties.$window_id,
                            properties.$current_url,
                            properties.$event_type,
                            properties.$screen_name,
                            properties.$pathname,
                            properties.$exception_type,
                            properties.$exception_message,
                            properties.$console_log_level,
                            properties.$response_status,
                            properties.$exception_list,
                            distinct_id
                        FROM events
                        WHERE timestamp >= UUIDv7ToDateTime(toUUID(${props.sessionId}))
                            AND timestamp <= UUIDv7ToDateTime(toUUID(${props.sessionId})) + INTERVAL 2 DAY
                            AND \`$session_id\` = ${props.sessionId}
                        ORDER BY timestamp ASC
                        LIMIT 50
                        OFFSET ${offset}
                    `
                            : hogql`
                        SELECT
                            uuid,
                            event,
                            timestamp,
                            properties.$window_id,
                            properties.$current_url,
                            properties.$event_type,
                            properties.$screen_name,
                            properties.$pathname,
                            properties.$exception_type,
                            properties.$exception_message,
                            properties.$console_log_level,
                            properties.$response_status,
                            properties.$exception_list,
                            distinct_id
                        FROM events
                        WHERE timestamp >= UUIDv7ToDateTime(toUUID(${props.sessionId}))
                            AND timestamp <= UUIDv7ToDateTime(toUUID(${props.sessionId})) + INTERVAL 2 DAY
                            AND \`$session_id\` = ${props.sessionId}
                        ORDER BY timestamp DESC
                        LIMIT 50
                        OFFSET ${offset}
                    `

                    const response = await api.queryHogQL(eventsQuery, {
                        scene: 'SessionProfile',
                        productKey: 'persons',
                    })

                    const newEvents = (response.results || []).map((row: any): SessionEventType => {
                        const properties: Record<string, any> = {}

                        if (row[3] != null) {
                            properties.$window_id = row[3]
                        }
                        if (row[4] != null) {
                            properties.$current_url = row[4]
                        }
                        if (row[5] != null) {
                            properties.$event_type = row[5]
                        }
                        if (row[6] != null) {
                            properties.$screen_name = row[6]
                        }
                        if (row[7] != null) {
                            properties.$pathname = row[7]
                        }
                        if (row[8] != null) {
                            properties.$exception_type = row[8]
                        }
                        if (row[9] != null) {
                            properties.$exception_message = row[9]
                        }
                        if (row[10] != null) {
                            properties.$console_log_level = row[10]
                        }
                        if (row[11] != null) {
                            properties.$response_status = row[11]
                        }

                        if (row[12] != null) {
                            try {
                                properties.$exception_list = JSON.parse(row[12])
                            } catch (e) {
                                console.error(e)
                                properties.$exception_list = []
                            }
                        }

                        return {
                            id: row[0],
                            event: row[1],
                            timestamp: row[2],
                            properties,
                            distinct_id: row[13],
                            fullyLoaded: false,
                        }
                    })

                    // Append new events to existing events
                    return [...currentEvents, ...newEvents]
                },
            },
        ],
        eventDetails: [
            {} as Record<string, Record<string, any>>,
            {
                loadEventDetails: async ({ eventId, eventName }) => {
                    // Fetch full properties for the specific event
                    // Use timestamp filtering based on session_id to enable partition pruning
                    // Also filter by event name to improve query performance
                    const detailsQuery = hogql`
                        SELECT properties, uuid
                        FROM events
                        WHERE event = ${eventName}
                        AND timestamp >= UUIDv7ToDateTime(toUUID(${props.sessionId}))
                        AND timestamp <= UUIDv7ToDateTime(toUUID(${props.sessionId})) + INTERVAL 2 DAY
                        AND uuid = ${eventId}
                        LIMIT 1
                    `

                    const response = await api.queryHogQL(detailsQuery, {
                        scene: 'SessionProfile',
                        productKey: 'persons',
                    })

                    if (!response.results || response.results.length === 0) {
                        return {}
                    }

                    const [propertiesJson, uuid] = response.results[0]
                    const fullProperties = JSON.parse(propertiesJson)

                    return { [uuid]: fullProperties }
                },
            },
        ],
        totalEventCount: [
            null as number | null,
            {
                loadTotalEventCount: async () => {
                    const countQuery = hogql`
                        SELECT count(*) as total
                        FROM events
                        WHERE timestamp >= UUIDv7ToDateTime(toUUID(${props.sessionId}))
                            AND timestamp <= UUIDv7ToDateTime(toUUID(${props.sessionId})) + INTERVAL 2 DAY
                            AND \`$session_id\` = ${props.sessionId}
                    `

                    const response = await api.queryHogQL(countQuery, {
                        scene: 'SessionProfile',
                        productKey: 'persons',
                    })
                    return response.results?.[0]?.[0] || 0
                },
            },
        ],
        hasRecording: [
            false as boolean,
            {
                loadRecordingAvailability: async () => {
                    // Extract timestamp from UUIDv7 for date filtering
                    const uuidHex = props.sessionId.replace(/-/g, '')
                    const timestampMs = parseInt(uuidHex.substring(0, 12), 16)
                    const startDate = new Date(timestampMs)
                    const endDate = new Date(timestampMs + 24 * 60 * 60 * 1000)

                    const response = await api.recordings.list({
                        kind: NodeKind.RecordingsQuery,
                        session_ids: [props.sessionId],
                        date_from: startDate.toISOString(),
                        date_to: endDate.toISOString(),
                        limit: 1,
                    })
                    return (response.results?.length ?? 0) > 0
                },
            },
        ],
        supportTicketEvents: [
            [] as SessionEventType[],
            {
                loadSupportTicketEvents: async () => {
                    const ticketsQuery = hogql`
                        SELECT
                            uuid,
                            event,
                            timestamp,
                            properties.zendesk_ticket_id,
                            distinct_id
                        FROM events
                        WHERE timestamp >= UUIDv7ToDateTime(toUUID(${props.sessionId}))
                            AND timestamp <= UUIDv7ToDateTime(toUUID(${props.sessionId})) + INTERVAL 2 DAY
                            AND \`$session_id\` = ${props.sessionId}
                            AND event = 'support_ticket'
                        ORDER BY timestamp DESC
                    `

                    const response = await api.queryHogQL(ticketsQuery, {
                        scene: 'SessionProfile',
                        productKey: 'persons',
                    })

                    return (response.results || []).map((row: any): SessionEventType => {
                        const properties: Record<string, any> = {}

                        if (row[3] != null) {
                            properties.zendesk_ticket_id = row[3]
                        }

                        return {
                            id: row[0],
                            event: row[1],
                            timestamp: row[2],
                            properties,
                            distinct_id: row[4],
                            fullyLoaded: false,
                        }
                    })
                },
            },
        ],
    })),
    selectors({
        sessionId: [() => [(_, props) => props.sessionId], (sessionId) => sessionId],
        sessionDuration: [
            (s) => [s.sessionData],
            (sessionData: SessionData | null): number | null => {
                // Session duration is already calculated in seconds in the table
                return sessionData?.session_duration || null
            },
        ],
        uniqueUrlCount: [
            (s) => [s.sessionData],
            (sessionData: SessionData | null): number => {
                return sessionData?.num_uniq_urls || 0
            },
        ],
        categorizedEventCount: [
            (s) => [s.sessionData],
            (sessionData: SessionData | null): number => {
                if (!sessionData) {
                    return 0
                }
                return (
                    (sessionData.pageview_count || 0) +
                    (sessionData.autocapture_count || 0) +
                    (sessionData.screen_count || 0)
                )
            },
        ],
        otherEventCount: [
            (s) => [s.totalEventCount, s.sessionData],
            (totalEventCount: number | null, sessionData: SessionData | null): number => {
                if (!totalEventCount || !sessionData) {
                    return 0
                }
                const categorized =
                    (sessionData.pageview_count || 0) +
                    (sessionData.autocapture_count || 0) +
                    (sessionData.screen_count || 0)
                return Math.max(0, totalEventCount - categorized)
            },
        ],
        isInitialLoading: [
            (s) => [s.sessionDataLoading, s.sessionEventsLoading, s.sessionData, s.sessionEvents],
            (
                sessionDataLoading: boolean,
                sessionEventsLoading: boolean,
                sessionData: SessionData | null,
                sessionEvents: SessionEventType[] | null
            ): boolean =>
                (sessionDataLoading && sessionData === null) || (sessionEventsLoading && sessionEvents === null),
        ],
        isLoadingMore: [
            (s) => [s.sessionEventsLoading, s.sessionEvents],
            (sessionEventsLoading: boolean, sessionEvents: SessionEventType[] | null): boolean =>
                sessionEventsLoading && sessionEvents !== null,
        ],
    }),
    listeners(({ actions, values }) => ({
        loadSessionData: () => {
            actions.loadSessionEvents()
            actions.loadTotalEventCount()
            actions.loadRecordingAvailability()
            actions.loadSupportTicketEvents()
        },
        setSortOrder: () => {
            // Reset hasMoreEvents when changing sort order
            actions.setHasMoreEvents(true)
            // Reload events with new sort order
            actions.loadSessionEvents()
        },
        loadMoreSessionEventsSuccess: ({ sessionEvents }) => {
            const previousCount = values.eventsOffset
            const newCount = sessionEvents.length
            const fetchedCount = newCount - previousCount

            // Stop loading if we fetched less than 50 events (or if something went wrong)
            if (fetchedCount < 50) {
                actions.setHasMoreEvents(false)
            }

            // Only update offset if we actually got new events
            if (fetchedCount > 0) {
                actions.updateEventsOffset(newCount)
            }
        },
        loadEventDetailsSuccess: ({ eventDetails }) => {
            // After loading event details, update the sessionEvents array
            const events = values.sessionEvents
            if (!events || !eventDetails || Object.keys(eventDetails).length === 0) {
                return
            }

            const updatedEvents = events.map((event) => {
                const fullProperties = eventDetails[event.id]
                if (fullProperties) {
                    return {
                        ...event,
                        properties: {
                            ...event.properties,
                            ...fullProperties,
                        },
                        fullyLoaded: true,
                    }
                }
                return event
            })

            actions.loadSessionEventsSuccess(updatedEvents)
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSessionData()
        },
    })),
])

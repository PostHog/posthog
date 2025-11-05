import { actions, events, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { hogql } from '~/queries/utils'
import { SessionEventType } from '~/types'

import type { sessionProfileLogicType } from './sessionProfileLogicType'

export interface SessionProfileLogicProps {
    sessionId: string
}

export interface SessionData {
    session_id: string
    distinct_id: string
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
        loadEventDetails: (eventId: string) => ({ eventId }),
    }),
    loaders(({ props }) => ({
        sessionData: [
            null as SessionData | null,
            {
                loadSessionData: async () => {
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
                        WHERE session_id = ${props.sessionId}
                        LIMIT 1
                    `

                    const response = await api.queryHogQL(sessionQuery)
                    const row = response.results?.[0]

                    if (!row) {
                        return null
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
                    }
                },
            },
        ],
        sessionEvents: [
            null as SessionEventType[] | null,
            {
                loadSessionEvents: async () => {
                    const eventsQuery = hogql`
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
                            AND timestamp <= UUIDv7ToDateTime(toUUID(${props.sessionId})) + INTERVAL 1 DAY
                            AND $session_id = ${props.sessionId}
                        ORDER BY timestamp ASC
                        LIMIT 10000
                    `

                    const response = await api.queryHogQL(eventsQuery)

                    return (response.results || []).map((row: any): SessionEventType => {
                        const properties: Record<string, any> = {}

                        // Only add properties if they have values (not null/undefined)
                        if (row[4] != null) {
                            properties.$window_id = row[4]
                        }
                        if (row[5] != null) {
                            properties.$current_url = row[5]
                        }
                        if (row[6] != null) {
                            properties.$event_type = row[6]
                        }
                        if (row[7] != null) {
                            properties.$screen_name = row[7]
                        }
                        if (row[8] != null) {
                            properties.$pathname = row[8]
                        }
                        if (row[9] != null) {
                            properties.$exception_type = row[9]
                        }
                        if (row[10] != null) {
                            properties.$exception_message = row[10]
                        }
                        if (row[11] != null) {
                            properties.$console_log_level = row[11]
                        }
                        if (row[12] != null) {
                            properties.$response_status = row[12]
                        }

                        // Parse $exception_list if it exists (comes as JSON string)
                        if (row[13] != null) {
                            try {
                                properties.$exception_list = JSON.parse(row[13])
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
                            distinct_id: row[14],
                            fullyLoaded: false,
                        }
                    })
                },
            },
        ],
        eventDetails: [
            {} as Record<string, Record<string, any>>,
            {
                loadEventDetails: async ({ eventId }) => {
                    // Fetch full properties for the specific event
                    const detailsQuery = hogql`
                        SELECT properties, uuid
                        FROM events
                        WHERE uuid = ${eventId}
                        LIMIT 1
                    `

                    const response = await api.queryHogQL(detailsQuery)

                    if (!response.results || response.results.length === 0) {
                        return {}
                    }

                    const [propertiesJson, uuid] = response.results[0]
                    const fullProperties = JSON.parse(propertiesJson)

                    return { [uuid]: fullProperties }
                },
            },
        ],
    })),
    selectors({
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
        totalEventCount: [
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
        isLoading: [
            (s) => [s.sessionDataLoading, s.sessionEventsLoading],
            (sessionDataLoading: boolean, sessionEventsLoading: boolean): boolean =>
                sessionDataLoading || sessionEventsLoading,
        ],
    }),
    listeners(({ actions, values }) => ({
        loadSessionData: () => {
            actions.loadSessionEvents()
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

import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { PERSON_DISPLAY_NAME_COLUMN_NAME } from 'lib/constants'

import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { SessionEventType } from '~/types'

import { teamLogic } from '../teamLogic'
import type { sessionProfileLogicType } from './sessionProfileLogicType'

/**
 * Extract the timestamp embedded in a UUIDv7.
 * UUIDv7 encodes the Unix timestamp in milliseconds in the first 48 bits.
 */
function getTimestampFromUUIDv7(sessionId: string): { startDate: Date; endDate: Date } {
    const uuidHex = sessionId.replace(/-/g, '')
    const timestampMs = parseInt(uuidHex.substring(0, 12), 16)
    const startDate = new Date(timestampMs)
    // Add 2 days buffer to ensure we capture all events for the session
    const endDate = new Date(timestampMs + 2 * 24 * 60 * 60 * 1000)
    return { startDate, endDate }
}

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

export const SESSION_EVENTS_CONTEXT_KEY = 'session-profile-events'

function createSessionEventsQuery(sessionId: string): DataTableNode {
    const { startDate } = getTimestampFromUUIDv7(sessionId)
    return {
        kind: NodeKind.DataTableNode,
        full: true,
        showEventsFilter: true,
        showTableViews: true,
        contextKey: SESSION_EVENTS_CONTEXT_KEY,
        hiddenColumns: [PERSON_DISPLAY_NAME_COLUMN_NAME],
        source: {
            kind: NodeKind.EventsQuery,
            select: defaultDataTableColumns(NodeKind.EventsQuery),
            where: [`\`$session_id\` = '${sessionId}'`],
            after: startDate.toISOString(),
            orderBy: ['timestamp ASC'],
        },
    }
}

export const sessionProfileLogic = kea<sessionProfileLogicType>([
    path(['scenes', 'sessions', 'sessionProfileLogic']),
    props({} as SessionProfileLogicProps),
    key((props) => props.sessionId),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    actions({
        loadSessionData: true,
        loadTotalEventCount: true,
        loadRecordingAvailability: true,
        loadSupportTicketEvents: true,
        setEventsQuery: (eventsQuery: DataTableNode) => ({ eventsQuery }),
    }),
    reducers(({ props }) => ({
        eventsQuery: [
            createSessionEventsQuery(props.sessionId),
            {
                setEventsQuery: (_, { eventsQuery }) => eventsQuery,
            },
        ],
    })),
    loaders(({ props, values }) => ({
        sessionData: [
            null as SessionData | null,
            {
                loadSessionData: async () => {
                    // Check the session table version to optimize the query
                    const { currentTeam } = values
                    const sessionTableVersion =
                        currentTeam?.modifiers?.sessionTableVersion ??
                        currentTeam?.default_modifiers?.sessionTableVersion ??
                        'auto'

                    // V3 uses session_id directly for a point lookup (converted to session_timestamp = exact)
                    // V2/AUTO needs timestamp hints due to cityHash64 in the ordering key
                    const sessionQuery =
                        sessionTableVersion === 'v3'
                            ? hogql`
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
                            : (() => {
                                  // Extract timestamp from UUIDv7 and use simple date constants
                                  // This allows ClickHouse to push predicates down for partition pruning
                                  const { startDate } = getTimestampFromUUIDv7(props.sessionId)
                                  const endDate = new Date(startDate.getTime() + 60 * 60 * 1000) // +1 hour
                                  return hogql`
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
                        WHERE $start_timestamp >= toDateTime(${startDate.toISOString()})
                            AND $start_timestamp <= toDateTime(${endDate.toISOString()})
                            AND session_id = ${props.sessionId}
                        LIMIT 1
                    `
                              })()

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
        totalEventCount: [
            null as number | null,
            {
                loadTotalEventCount: async () => {
                    const { startDate, endDate } = getTimestampFromUUIDv7(props.sessionId)
                    const countQuery = hogql`
                        SELECT count(*) as total
                        FROM events
                        WHERE timestamp >= toDateTime(${startDate.toISOString()})
                            AND timestamp <= toDateTime(${endDate.toISOString()})
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
                    const { startDate } = getTimestampFromUUIDv7(props.sessionId)
                    // Only need +1 day for recording availability check
                    const endDate = new Date(startDate.getTime() + 24 * 60 * 60 * 1000)

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
                    const { startDate, endDate } = getTimestampFromUUIDv7(props.sessionId)
                    const ticketsQuery = hogql`
                        SELECT
                            uuid,
                            event,
                            timestamp,
                            properties.zendesk_ticket_id,
                            distinct_id
                        FROM events
                        WHERE timestamp >= toDateTime(${startDate.toISOString()})
                            AND timestamp <= toDateTime(${endDate.toISOString()})
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
        sessionProperties: [
            (s) => [s.sessionData],
            (sessionData: SessionData | null): Record<string, any> | null => {
                if (!sessionData) {
                    return null
                }

                const props: Record<string, any> = {}
                const mappings: [string, any][] = [
                    ['$session_duration', sessionData.session_duration],
                    ['$start_timestamp', sessionData.start_timestamp],
                    ['$end_timestamp', sessionData.end_timestamp],
                    ['$entry_current_url', sessionData.entry_current_url],
                    ['$end_current_url', sessionData.end_current_url],
                    ['$urls', sessionData.urls?.length ? sessionData.urls : null],
                    ['$pageview_count', sessionData.pageview_count],
                    ['$autocapture_count', sessionData.autocapture_count],
                    ['$screen_count', sessionData.screen_count],
                    ['$channel_type', sessionData.channel_type],
                    ['$is_bounce', sessionData.is_bounce],
                    ['$entry_hostname', sessionData.entry_hostname],
                    ['$entry_pathname', sessionData.entry_pathname],
                    ['$entry_utm_source', sessionData.entry_utm_source],
                    ['$entry_utm_campaign', sessionData.entry_utm_campaign],
                    ['$entry_utm_medium', sessionData.entry_utm_medium],
                    ['$entry_referring_domain', sessionData.entry_referring_domain],
                    ['$last_external_click_url', sessionData.last_external_click_url],
                ]

                for (const [key, value] of mappings) {
                    if (value != null) {
                        props[key] = value
                    }
                }

                return props
            },
        ],
    }),
    listeners(({ actions }) => ({
        loadSessionData: () => {
            actions.loadTotalEventCount()
            actions.loadRecordingAvailability()
            actions.loadSupportTicketEvents()
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadSessionData()
        },
    })),
])

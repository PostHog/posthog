import { actions, events, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { hogql } from '~/queries/utils'
import { RecordingEventType } from '~/types'

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
            null as RecordingEventType[] | null,
            {
                loadSessionEvents: async () => {
                    const eventsQuery = hogql`
                        SELECT
                            uuid,
                            event,
                            timestamp,
                            elements_chain,
                            properties.$window_id,
                            properties.$current_url,
                            properties.$event_type,
                            properties,
                            distinct_id
                        FROM events
                        WHERE $session_id = ${props.sessionId}
                        ORDER BY timestamp ASC
                        LIMIT 10000
                    `

                    const response = await api.queryHogQL(eventsQuery)

                    return (response.results || []).map((row: any): RecordingEventType => {
                        return {
                            id: row[0],
                            event: row[1],
                            timestamp: row[2],
                            properties: {
                                ...row[7],
                                $window_id: row[4],
                                $current_url: row[5],
                                $event_type: row[6],
                            },
                            distinct_id: row[8],
                            fullyLoaded: false,
                        }
                    })
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
    listeners(({ actions }) => ({
        loadSessionData: () => {
            console.log('JFBW: Loading session data')
            actions.loadSessionEvents()
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            console.log('JFBW: Logic mounted, loading session data')
            actions.loadSessionData()
        },
    })),
])

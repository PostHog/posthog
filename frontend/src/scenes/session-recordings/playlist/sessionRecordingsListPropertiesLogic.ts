import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import { hogql } from '~/queries/utils'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { SessionRecordingPropertiesType, SessionRecordingType } from '~/types'

import type { sessionRecordingsListPropertiesLogicType } from './sessionRecordingsListPropertiesLogicType'

// This logic is used to fetch properties for a list of recordings
// It is used in a global way as the cached values can be re-used
export const sessionRecordingsListPropertiesLogic = kea<sessionRecordingsListPropertiesLogicType>([
    path(() => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsListPropertiesLogic']),
    connect(() => ({
        actions: [sessionRecordingEventUsageLogic, ['reportRecordingsListPropertiesFetched']],
    })),

    actions({
        loadPropertiesForSessions: (sessions: SessionRecordingType[]) => ({ sessions }),
        maybeLoadPropertiesForSessions: (sessions: SessionRecordingType[]) => ({ sessions }),
    }),

    loaders(({ actions }) => ({
        recordingProperties: [
            [] as SessionRecordingPropertiesType[],
            {
                loadPropertiesForSessions: async ({ sessions }, breakpoint) => {
                    await breakpoint(100)

                    const startTime = performance.now()
                    const sessionIds = sessions.map((x) => x.id)

                    const oldestTimestamp = sessions.map((x) => x.start_time).sort()[0]
                    const newestTimestamp = sessions.map((x) => x.end_time).sort()[sessions.length - 1]

                    const query = hogql`
                        SELECT 
                            $session_id as session_id, 
                            any(properties.$geoip_country_code) as $geoip_country_code, 
                            any(properties.$browser) as $browser, 
                            any(properties.$device_type) as $device_type, 
                            any(properties.$os) as $os, 
                            any(properties.$os_name) as $os_name,
                            any(session.$entry_referring_domain) as $entry_referring_domain,
                            any(properties.$geoip_subdivision_1_name) as $geoip_subdivision_1_name,
                            any(properties.$geoip_city_name) as $geoip_city_name,
                            any(session.$entry_current_url) as $entry_current_url
                        FROM events
                        WHERE event IN ${Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP['events'])}
                        AND session_id IN ${sessionIds}
                        -- the timestamp range here is only to avoid querying too much of the events table
                        -- we don't really care about the absolute value, 
                        -- but we do care about whether timezones have an odd impact
                        -- so, we extend the range by a day on each side so that timezones don't cause issues
                        AND timestamp >= ${dayjs(oldestTimestamp).subtract(1, 'day')}
                        AND timestamp <= ${dayjs(newestTimestamp).add(1, 'day')}
                        GROUP BY session_id`

                    const response = await api.queryHogQL(query)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListPropertiesFetched(loadTimeMs)

                    breakpoint()
                    return (response.results || []).map((x: any): SessionRecordingPropertiesType => {
                        return {
                            id: x[0],
                            properties: {
                                $geoip_country_code: x[1],
                                $browser: x[2],
                                $device_type: x[3],
                                $os: x[4],
                                $os_name: x[5],
                                $entry_referring_domain: x[6],
                                $geoip_subdivision_1_name: x[7],
                                $geoip_city_name: x[8],
                                $entry_current_url: x[9],
                            },
                        }
                    })
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        maybeLoadPropertiesForSessions: ({ sessions }) => {
            const newSessions = sessions.filter((session) => !values.recordingPropertiesById[session.id])

            if (newSessions.length > 0) {
                actions.loadPropertiesForSessions(newSessions)
            }
        },
    })),

    reducers({
        recordingPropertiesById: [
            {} as Record<string, SessionRecordingPropertiesType['properties']>,
            {
                loadPropertiesForSessionsSuccess: (
                    state,
                    { recordingProperties }
                ): Record<string, SessionRecordingPropertiesType['properties']> => {
                    const newState = { ...state }
                    recordingProperties.forEach((properties) => {
                        if (properties.properties) {
                            newState[properties.id] = properties.properties
                        }
                    })

                    return newState
                },
            },
        ],
    }),
])

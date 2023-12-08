import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'
import { SessionRecordingPropertiesType, SessionRecordingType } from '~/types'

import type { sessionRecordingsListPropertiesLogicType } from './sessionRecordingsListPropertiesLogicType'

// This logic is used to fetch properties for a list of recordings
// It is used in a global way as the cached values can be re-used
export const sessionRecordingsListPropertiesLogic = kea<sessionRecordingsListPropertiesLogicType>([
    path(() => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsListPropertiesLogic']),
    connect(() => ({
        actions: [eventUsageLogic, ['reportRecordingsListPropertiesFetched']],
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

                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT properties.$session_id as session_id, any(properties) as properties
                                FROM events
                                WHERE event IN ['$pageview', '$autocapture']
                                AND session_id IN ${sessionIds}
                                -- the timestamp range here is only to avoid querying too much of the events table
                                -- we don't really care about the absolute value, 
                                -- but we do care about whether timezones have an odd impact
                                -- so, we extend the range by a day on each side so that timezones don't cause issues
                                AND timestamp >= ${dayjs(oldestTimestamp).subtract(1, 'day')}
                                AND timestamp <= ${dayjs(newestTimestamp).add(1, 'day')}
                                GROUP BY session_id`,
                    }

                    const response = await api.query(query)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListPropertiesFetched(loadTimeMs)

                    breakpoint()
                    return (response.results || []).map(
                        (x: any): SessionRecordingPropertiesType => ({
                            id: x[0],
                            properties: JSON.parse(x[1] || '{}'),
                        })
                    )
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
                        newState[properties.id] = properties.properties
                    })

                    return newState
                },
            },
        ],
    }),
])

import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { sessionRecordingEventUsageLogic } from 'scenes/session-recordings/sessionRecordingEventUsageLogic'

import { QueryLogTags } from '~/queries/schema/schema-general'
import { HogQLQueryString, escapePropertyAsHogQLIdentifier, hogql } from '~/queries/utils'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { SessionRecordingPropertiesType, SessionRecordingType } from '~/types'

import { sessionRecordingPinnedPropertiesLogic } from '../player/player-meta/sessionRecordingPinnedPropertiesLogic'
import type { sessionRecordingsListPropertiesLogicType } from './sessionRecordingsListPropertiesLogicType'

const QUERY_TAGS: QueryLogTags = { scene: 'Replay', productKey: 'session_replay' }

// [source table, property] pairs; order defines the result columns
const BASE_QUERY_PROPERTIES: [string, string][] = [
    ['properties', '$geoip_country_code'],
    ['properties', '$browser'],
    ['properties', '$device_type'],
    ['properties', '$os'],
    ['properties', '$os_name'],
    ['session', '$entry_referring_domain'],
    ['properties', '$geoip_subdivision_1_name'],
    ['properties', '$geoip_city_name'],
    ['session', '$entry_current_url'],
]
const BASE_PROPERTIES = BASE_QUERY_PROPERTIES.map(([, property]) => property)

function pinnedSessionProperties(pinnedProperties: string[]): string[] {
    return pinnedProperties.filter(
        (property) =>
            Object.hasOwn(CORE_FILTER_DEFINITIONS_BY_GROUP.session_properties, property) &&
            !BASE_PROPERTIES.includes(property)
    )
}

function buildPropertiesQuery(
    sessionIds: string[],
    oldestTimestamp: string,
    newestTimestamp: string | undefined,
    extraSessionProperties: string[]
): HogQLQueryString {
    const selects = [
        ...BASE_QUERY_PROPERTIES,
        ...extraSessionProperties.map((property): [string, string] => ['session', property]),
    ]
        .map(([source, property]) => {
            const identifier = escapePropertyAsHogQLIdentifier(property)
            return `any(${source}.${identifier}) as ${identifier}`
        })
        .join(',\n                            ')

    return hogql`
                        SELECT
                            $session_id as session_id,
                            ${hogql.raw(selects)}
                        FROM events
                        WHERE event IN ${Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP['events'])}
                        AND session_id IN ${sessionIds}
                        -- the timestamp range only bounds the events-table scan, padded a day each side so timezones can't cause issues
                        AND timestamp >= ${dayjs(oldestTimestamp).subtract(1, 'day')}
                        AND timestamp <= ${dayjs(newestTimestamp).add(1, 'day')}
                        GROUP BY session_id`
}

// This logic is used to fetch properties for a list of recordings
// It is used in a global way as the cached values can be re-used
export const sessionRecordingsListPropertiesLogic = kea<sessionRecordingsListPropertiesLogicType>([
    path(() => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsListPropertiesLogic']),
    connect(() => ({
        actions: [sessionRecordingEventUsageLogic, ['reportRecordingsListPropertiesFetched']],
        values: [sessionRecordingPinnedPropertiesLogic, ['pinnedProperties']],
    })),

    actions({
        loadPropertiesForSessions: (sessions: SessionRecordingType[]) => ({ sessions }),
        maybeLoadPropertiesForSessions: (sessions: SessionRecordingType[]) => ({ sessions }),
        markExtraPropertiesUnqueryable: (properties: string[]) => ({ properties }),
    }),

    loaders(({ actions, values }) => ({
        recordingProperties: [
            [] as SessionRecordingPropertiesType[],
            {
                loadPropertiesForSessions: async ({ sessions }, breakpoint) => {
                    await breakpoint(100)

                    const startTime = performance.now()
                    const sessionIds = sessions.map((x) => x.id)

                    const chronological = (a: string, b: string): number =>
                        new Date(a).getTime() - new Date(b).getTime()
                    const oldestTimestamp = sessions.map((x) => x.start_time).sort(chronological)[0]
                    const newestTimestamp = sessions.map((x) => x.end_time).sort(chronological)[sessions.length - 1]

                    const extraSessionProperties = values.extraSessionProperties
                    let response
                    try {
                        response = await api.queryHogQL(
                            buildPropertiesQuery(sessionIds, oldestTimestamp, newestTimestamp, extraSessionProperties),
                            QUERY_TAGS
                        )
                    } catch (e) {
                        if (!extraSessionProperties.length) {
                            throw e
                        }
                        response = await api.queryHogQL(
                            buildPropertiesQuery(sessionIds, oldestTimestamp, newestTimestamp, []),
                            QUERY_TAGS
                        )
                        // only a 400 (a pin missing from this project's session table) blacklists the pin set — transient errors retry next batch
                        if (e instanceof ApiError && e.status === 400) {
                            actions.markExtraPropertiesUnqueryable(extraSessionProperties)
                        }
                    }
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListPropertiesFetched(loadTimeMs)

                    breakpoint()
                    return (response.results || []).map((row: any[]): SessionRecordingPropertiesType => {
                        const cachedProperties = values.recordingPropertiesById[row[0]]
                        const properties: Record<string, any> = {}
                        BASE_PROPERTIES.forEach((property, index) => {
                            properties[property] = row[index + 1]
                        })
                        // fallback rows have no extra columns — keep cached values (or null) so entries read as complete
                        extraSessionProperties.forEach((property, index) => {
                            properties[property] =
                                row[BASE_PROPERTIES.length + 1 + index] ?? cachedProperties?.[property] ?? null
                        })
                        return { id: row[0], properties }
                    })
                },
            },
        ],
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
        unqueryableExtraProperties: [
            null as string[] | null,
            {
                markExtraPropertiesUnqueryable: (_, { properties }) => properties,
            },
        ],
    }),

    selectors({
        extraSessionProperties: [
            (s) => [s.pinnedProperties, s.unqueryableExtraProperties],
            (pinnedProperties, unqueryableExtraProperties): string[] => {
                const extras = pinnedSessionProperties(pinnedProperties)
                // while the pin set that failed to query is unchanged, don't retry it
                if (
                    unqueryableExtraProperties &&
                    extras.length === unqueryableExtraProperties.length &&
                    extras.every((property, index) => property === unqueryableExtraProperties[index])
                ) {
                    return []
                }
                return extras
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        maybeLoadPropertiesForSessions: ({ sessions }) => {
            const wantedSessionProperties = values.extraSessionProperties
            const newSessions = sessions.filter((session) => {
                const cached = values.recordingPropertiesById[session.id]
                return !cached || wantedSessionProperties.some((property) => !(property in cached))
            })

            if (newSessions.length > 0) {
                actions.loadPropertiesForSessions(newSessions)
            }
        },
    })),
])

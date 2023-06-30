import { connect, kea, path, reducers, actions, listeners } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { SessionRecordingPropertiesType } from '~/types'
import { toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import type { sessionRecordingsListPropertiesLogicType } from './sessionRecordingsListPropertiesLogicType'

// This logic is used to fetch properties for a list of recordings
// It is used in a global way as the cached values can be re-used
export const sessionRecordingsListPropertiesLogic = kea<sessionRecordingsListPropertiesLogicType>([
    path(() => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsListPropertiesLogic']),
    connect(() => ({
        actions: [eventUsageLogic, ['reportRecordingsListPropertiesFetched']],
    })),

    actions({
        loadPropertiesForSessions: (ids: string[]) => ({ ids }),
        maybeLoadPropertiesForSessions: (ids: string[]) => ({ ids }),
    }),

    loaders(({ actions }) => ({
        recordingProperties: [
            [] as SessionRecordingPropertiesType[],
            {
                loadPropertiesForSessions: async ({ ids }, breakpoint) => {
                    const paramsDict = {
                        session_ids: ids,
                    }
                    const params = toParams(paramsDict)
                    await breakpoint(100)

                    const startTime = performance.now()
                    const response = await api.recordings.listProperties(params)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListPropertiesFetched(loadTimeMs)

                    breakpoint()
                    return response.results
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        maybeLoadPropertiesForSessions: ({ ids }) => {
            // Check the cache store and only load if not already loaded
            const newSessionIds = ids.filter((id) => !values.recordingPropertiesById[id])

            if (newSessionIds.length > 0) {
                actions.loadPropertiesForSessions(newSessionIds)
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

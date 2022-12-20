import { connect, kea, key, props, path, selectors, propsChanged } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { SessionRecordingPropertiesType, SessionRecordingType } from '~/types'
import { toParams } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import type { sessionRecordingsListPropertiesLogicType } from './sessionRecordingsListPropertiesLogicType'
import equal from 'fast-deep-equal'

export interface SessionRecordingsListPropertiesLogicProps {
    key: string
    sessionIds: SessionRecordingType['id'][]
}

export const sessionRecordingsListPropertiesLogic = kea<sessionRecordingsListPropertiesLogicType>([
    path((key) => ['scenes', 'session-recordings', 'playlist', 'sessionRecordingsListPropertiesLogic', key]),
    props({} as SessionRecordingsListPropertiesLogicProps),
    key((props) => props.key),
    connect(() => ({
        actions: [eventUsageLogic, ['reportRecordingsListPropertiesFetched']],
    })),
    propsChanged(({ actions, props: { sessionIds } }, { sessionIds: oldSessionIds }) => {
        if (!equal(sessionIds, oldSessionIds)) {
            actions.getSessionRecordingsProperties(sessionIds ?? [])
        }
    }),
    loaders(({ actions }) => ({
        sessionRecordingsPropertiesResponse: [
            {
                results: [],
            } as PaginatedResponse<SessionRecordingPropertiesType>,
            {
                getSessionRecordingsProperties: async (sessionIds, breakpoint) => {
                    if (sessionIds.length < 1) {
                        return {
                            results: [],
                        }
                    }
                    const paramsDict = {
                        session_ids: sessionIds,
                    }
                    const params = toParams(paramsDict)
                    await breakpoint(100) // Debounce for lots of quick filter changes

                    const startTime = performance.now()
                    const response = await api.recordings.listProperties(params)
                    const loadTimeMs = performance.now() - startTime

                    actions.reportRecordingsListPropertiesFetched(loadTimeMs)

                    breakpoint()
                    return response
                },
            },
        ],
    })),
    selectors(() => ({
        sessionRecordingIdToProperties: [
            (s) => [s.sessionRecordingsPropertiesResponse],
            (propertiesResponse: PaginatedResponse<SessionRecordingPropertiesType>) => {
                return (
                    Object.fromEntries(propertiesResponse.results.map(({ id, properties }) => [id, properties])) ?? {}
                )
            },
        ],
    })),
])

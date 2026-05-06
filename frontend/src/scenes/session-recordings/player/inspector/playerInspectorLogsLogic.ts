import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { LogMessage, LogsQuery } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { sessionRecordingDataCoordinatorLogic } from '../sessionRecordingDataCoordinatorLogic'
import { SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import type { playerInspectorLogsLogicType } from './playerInspectorLogsLogicType'

export const MAX_LOG_ENTRIES = 5000

export function buildSessionLogsQuery(
    sessionId: string,
    start: Dayjs,
    end: Dayjs,
    cursor?: string
): Omit<LogsQuery, 'kind'> {
    return {
        dateRange: {
            date_from: start.toISOString(),
            date_to: end.toISOString(),
        },
        filterGroup: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            key: 'session_id',
                            value: sessionId,
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.LogAttribute,
                        },
                    ],
                },
            ],
        },
        severityLevels: [],
        serviceNames: [],
        orderBy: 'earliest',
        limit: 1000,
        ...(cursor ? { after: cursor } : {}),
    }
}

export const playerInspectorLogsLogic = kea<playerInspectorLogsLogicType>([
    path((key) => ['scenes', 'session-recordings', 'player', 'inspector', 'playerInspectorLogsLogic', key]),
    props({} as SessionRecordingPlayerLogicProps),
    key((props: SessionRecordingPlayerLogicProps) => `${props.playerKey}-${props.sessionRecordingId}`),
    connect((props: SessionRecordingPlayerLogicProps) => ({
        values: [sessionRecordingDataCoordinatorLogic(props), ['start', 'end'], featureFlagLogic, ['featureFlags']],
    })),
    actions(() => ({
        setLogsHasMore: (hasMore: boolean) => ({ hasMore }),
        setLogsNextCursor: (cursor: string | undefined) => ({ cursor }),
        markLogsInitialLoadRequested: true,
    })),
    reducers(() => ({
        logsHasMore: [
            false,
            {
                setLogsHasMore: (_, { hasMore }) => hasMore,
            },
        ],
        logsNextCursor: [
            undefined as string | undefined,
            {
                setLogsNextCursor: (_, { cursor }) => cursor,
            },
        ],
        logsInitialLoadRequested: [
            false,
            {
                markLogsInitialLoadRequested: () => true,
            },
        ],
        logsLoadError: [
            false,
            {
                loadLogs: () => false,
                loadLogsSuccess: () => false,
                loadLogsFailure: () => true,
                loadMoreLogs: () => false,
                loadMoreLogsSuccess: () => false,
                loadMoreLogsFailure: () => true,
            },
        ],
    })),
    loaders(({ actions, values, props }) => ({
        logs: [
            [] as LogMessage[],
            {
                loadLogs: async () => {
                    if (!values.featureFlags[FEATURE_FLAGS.SESSION_REPLAY_BACKEND_LOGS]) {
                        return []
                    }

                    if (!props.sessionRecordingId || !values.start || !values.end) {
                        return []
                    }

                    try {
                        const response = await api.logs.query({
                            query: buildSessionLogsQuery(props.sessionRecordingId, values.start, values.end),
                        })
                        actions.setLogsHasMore(response.hasMore)
                        actions.setLogsNextCursor(response.nextCursor)
                        return response.results
                    } catch (error) {
                        console.error('Failed to load backend logs for session replay', error)
                        throw error
                    }
                },
                loadMoreLogs: async () => {
                    const cursor = values.logsNextCursor
                    if (!cursor || !values.start || !values.end) {
                        return values.logs
                    }

                    if (values.logs.length >= MAX_LOG_ENTRIES) {
                        actions.setLogsHasMore(false)
                        return values.logs
                    }

                    try {
                        const response = await api.logs.query({
                            query: buildSessionLogsQuery(props.sessionRecordingId, values.start, values.end, cursor),
                        })
                        const combined = [...values.logs, ...response.results]
                        const capped = combined.length >= MAX_LOG_ENTRIES
                        actions.setLogsHasMore(capped ? false : response.hasMore)
                        actions.setLogsNextCursor(capped ? undefined : response.nextCursor)
                        return capped ? combined.slice(0, MAX_LOG_ENTRIES) : combined
                    } catch (error) {
                        console.error('Failed to load more backend logs for session replay', error)
                        throw error
                    }
                },
            },
        ],
    })),
    selectors(() => ({
        readyToLoadLogs: [
            (s) => [s.featureFlags, s.start, s.end, (_, props) => props.sessionRecordingId],
            (featureFlags, start, end, sessionRecordingId): boolean =>
                !!featureFlags[FEATURE_FLAGS.SESSION_REPLAY_BACKEND_LOGS] && !!start && !!end && !!sessionRecordingId,
        ],
    })),
])

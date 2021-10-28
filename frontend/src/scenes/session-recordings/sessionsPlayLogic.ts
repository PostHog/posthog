import { kea } from 'kea'
import api from 'lib/api'
import { errorToast, toParams } from 'lib/utils'
import { sessionsPlayLogicType } from './sessionsPlayLogicType'
import { SessionPlayerData, SessionRecordingId, SessionRecordingMeta, SessionRecordingUsageType } from '~/types'
import dayjs from 'dayjs'
import { eventUsageLogic, RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { teamLogic } from '../teamLogic'
import { eventWithTime } from 'rrweb/typings/types'

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export const parseMetadataResponse = (metadata: Record<string, any>): Partial<SessionRecordingMeta> => {
    return {
        ...(metadata ?? {}),
        start_time: metadata?.start_time ? +dayjs(metadata?.start_time) : 0,
        end_time: metadata?.end_time ? +dayjs(metadata?.end_time) : 0,
        recording_duration: parseFloat(metadata?.recording_duration) * 1000 || 0, // s to ms
    }
}

export const sessionsPlayLogic = kea<sessionsPlayLogicType>({
    connect: {
        logic: [eventUsageLogic],
        values: [teamLogic, ['currentTeamId']],
    },
    actions: {
        setSource: (source: RecordingWatchedSource) => ({ source }),
        reportUsage: (recordingData: SessionPlayerData, loadTime: number) => ({
            recordingData,
            loadTime,
        }),
        loadRecordingMeta: (sessionRecordingId?: string) => ({ sessionRecordingId }),
        loadRecordingSnapshots: (sessionRecordingId?: string, url?: string) => ({ sessionRecordingId, url }),
    },
    reducers: {
        sessionRecordingId: [
            null as SessionRecordingId | null,
            {
                loadRecording: (_, { sessionRecordingId }) => sessionRecordingId ?? null,
            },
        ],
        chunkPaginationIndex: [
            0,
            {
                loadRecordingSnapshotsSuccess: (state) => state + 1,
            },
        ],
        sessionPlayerDataLoading: [
            false,
            {
                loadRecordingSnapshotsSuccess: (_, { sessionPlayerData }) => {
                    // If sessionPlayerData doesn't have a next url, it means the entire recording is still loading.
                    return !!sessionPlayerData?.next
                },
            },
        ],
        source: [
            RecordingWatchedSource.Unknown as RecordingWatchedSource,
            {
                setSource: (_, { source }) => source,
            },
        ],
    },
    listeners: ({ values, actions, sharedListeners, cache }) => ({
        loadRecordingSnapshotsSuccess: async () => {
            // If there is more data to poll for load the next batch.
            // This will keep calling loadRecording until `next` is empty.
            if (!!values.sessionPlayerData?.next) {
                await actions.loadRecordingSnapshots(undefined, values.sessionPlayerData.next)
            }
            // Finished loading entire recording. Now make it known!
            else {
                eventUsageLogic.actions.reportRecording(
                    values.sessionPlayerData,
                    values.source,
                    performance.now() - cache.startTime,
                    SessionRecordingUsageType.LOADED,
                    0
                )
            }
            // Not always accurate that recording is playable after first chunk is loaded, but good guesstimate for now
            if (values.chunkPaginationIndex === 1) {
                actions.reportUsage(values.sessionPlayerData, performance.now() - cache.startTime)
            }
        },
        loadRecordingMetaFailure: sharedListeners.showErrorToast,
        loadRecordingSnapshotsFailure: sharedListeners.showErrorToast,
        reportUsage: async ({ recordingData, loadTime }, breakpoint) => {
            await breakpoint()
            eventUsageLogic.actions.reportRecording(
                recordingData,
                values.source,
                loadTime,
                SessionRecordingUsageType.VIEWED,
                0
            )
            await breakpoint(IS_TEST_MODE ? 1 : 10000)
            eventUsageLogic.actions.reportRecording(
                recordingData,
                values.source,
                loadTime,
                SessionRecordingUsageType.ANALYZED,
                10
            )
        },
    }),
    sharedListeners: () => ({
        showErrorToast: ({ error }) => {
            errorToast(
                'Error fetching information for your session recording',
                'The following error response was returned:',
                error
            )
        },
    }),
    loaders: ({ values }) => ({
        sessionPlayerData: {
            loadRecordingMeta: async ({ sessionRecordingId }): Promise<SessionPlayerData> => {
                const params = toParams({ save_view: true })
                const response = await api.get(
                    `api/projects/${values.currentTeamId}/session_recordings/${sessionRecordingId}?${params}`
                )

                return {
                    ...response.result,
                    session_recording: parseMetadataResponse(response.result?.session_recording),
                    snapshots: values.sessionPlayerData?.snapshots ?? [], // don't override snapshots
                }
            },
            loadRecordingSnapshots: async ({ sessionRecordingId, url }): Promise<SessionPlayerData> => {
                let response
                if (url) {
                    // Subsequent calls to get rest of recording
                    response = await api.get(url)
                } else {
                    // Very first call
                    response = await api.get(
                        `api/projects/${values.currentTeamId}/session_recordings/${sessionRecordingId}/snapshots`
                    )
                }
                const currData = values.sessionPlayerData
                return {
                    ...currData,
                    next: response.result?.next,
                    snapshots: [...(currData?.snapshots ?? []), ...(response.result?.snapshots ?? [])],
                }
            },
        },
    }),
    selectors: {
        firstChunkLoaded: [
            (selectors) => [selectors.chunkPaginationIndex],
            (chunkPaginationIndex) => chunkPaginationIndex > 0,
        ],
        isPlayable: [
            (selectors) => [
                selectors.firstChunkLoaded,
                selectors.sessionPlayerDataLoading,
                selectors.sessionPlayerData,
            ],
            (firstChunkLoaded, sessionPlayerDataLoading, sessionPlayerData) =>
                (firstChunkLoaded || // If first chunk is ready
                    !sessionPlayerDataLoading) && // data isn't being fetched
                sessionPlayerData?.snapshots.length > 1 && // more than one snapshot needed to init rrweb Replayer
                !!sessionPlayerData?.snapshots?.find((s: eventWithTime) => s.type === 2), // there's a full snapshot in the data that was loaded
        ],
    },
    urlToAction: ({ actions, values, cache }) => {
        const urlToAction = (
            _: any,
            params: {
                sessionRecordingId?: SessionRecordingId
                source?: string
            }
        ): void => {
            const { sessionRecordingId, source } = params
            if (source && (Object.values(RecordingWatchedSource) as string[]).includes(source)) {
                actions.setSource(source as RecordingWatchedSource)
            }
            if (values && sessionRecordingId !== values.sessionRecordingId && sessionRecordingId) {
                // Load meta first. Snapshots are loaded once Replayer ref is mounted in sessionRecordingPlayerLogic
                cache.startTime = performance.now()
                actions.loadRecordingMeta(sessionRecordingId)
                actions.loadRecordingSnapshots(sessionRecordingId)
            }
        }

        return {
            '/sessions': urlToAction,
            '/recordings': urlToAction,
            '/person/*': urlToAction,
        }
    },
})

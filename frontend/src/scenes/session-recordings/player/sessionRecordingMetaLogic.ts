import { actions, connect, defaults, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { snapshotDataLogic } from 'scenes/session-recordings/player/snapshotDataLogic'
import { windowIdRegistryLogic } from 'scenes/session-recordings/player/windowIdRegistryLogic'
import { teamLogic } from 'scenes/teamLogic'

import { annotationsModel } from '~/models/annotationsModel'
import { SessionRecordingId, SessionRecordingType } from '~/types'

import { ExportedSessionRecordingFileV2 } from '../file-playback/types'
import type { sessionRecordingMetaLogicType } from './sessionRecordingMetaLogicType'

export interface SessionRecordingMetaLogicProps {
    sessionRecordingId: SessionRecordingId
    blobV2PollingDisabled?: boolean
    playerKey?: string
    accessToken?: string
}

export const sessionRecordingMetaLogic = kea<sessionRecordingMetaLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionRecordingMetaLogic', key]),
    props({} as SessionRecordingMetaLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect(({ sessionRecordingId, blobV2PollingDisabled }: SessionRecordingMetaLogicProps) => {
        const snapshotLogic = snapshotDataLogic({
            sessionRecordingId,
            blobV2PollingDisabled,
        })
        const registryLogic = windowIdRegistryLogic({ sessionRecordingId })
        return {
            actions: [
                snapshotLogic,
                ['loadSnapshots', 'loadSnapshotSources', 'loadSnapshotsForSourceSuccess', 'setSnapshots'],
                registryLogic,
                ['registerWindowId'],
            ],
            values: [
                teamLogic,
                ['currentTeam'],
                annotationsModel,
                ['annotations', 'annotationsLoading'],
                snapshotLogic,
                [
                    'snapshotSources',
                    'snapshotsLoading',
                    'snapshotsLoaded',
                    'isLoadingSnapshots',
                    'isRecordingDeleted',
                    'recordingDeletedAt',
                    'recordingDeletedBy',
                ],
                registryLogic,
                ['uuidToIndex', 'getWindowId'],
            ],
        }
    }),
    defaults({
        sessionPlayerMetaData: null as SessionRecordingType | null,
    }),
    actions({
        loadRecordingMeta: true,
        loadRecordingFromFile: (recording: ExportedSessionRecordingFileV2['data']) => ({ recording }),
        maybeLoadRecordingMeta: true,
        setTrackedWindow: (windowId: number | null) => ({ windowId }),
    }),
    reducers(() => ({
        isNotFound: [
            false as boolean,
            {
                loadRecordingMeta: () => false,
                loadRecordingMetaSuccess: () => false,
                loadRecordingMetaFailure: (_, { errorObject }) =>
                    errorObject instanceof ApiError && errorObject.status === 404,
            },
        ],
        loadMetaError: [
            false as boolean,
            {
                loadRecordingMeta: () => false,
                loadRecordingMetaSuccess: () => false,
                loadRecordingMetaFailure: (_, { errorObject }) =>
                    !(errorObject instanceof ApiError && errorObject.status === 404),
            },
        ],
        trackedWindow: [
            null as number | null,
            {
                setTrackedWindow: (_, { windowId }) => windowId,
            },
        ],
    })),
    loaders(({ props }) => ({
        sessionPlayerMetaData: {
            loadRecordingMeta: async (_, breakpoint) => {
                if (!props.sessionRecordingId) {
                    return null
                }
                // Cancel orphaned loaders from StrictMode's unmounted logic
                await breakpoint(1)
                const headers: Record<string, string> = {}
                if (props.accessToken) {
                    headers.Authorization = `Bearer ${props.accessToken}`
                }
                try {
                    const response = await api.recordings.get(props.sessionRecordingId, {}, headers)
                    breakpoint()
                    return response
                } catch (error) {
                    // Breakpoint cancellation — let kea-loaders swallow it silently.
                    if ((error as Error | null)?.name === 'AbortError') {
                        throw error
                    }
                    // HTTP-level failures (404, 403, 5xx) flow through unchanged so the
                    // existing `isNotFound` / `loadMetaError` reducers keep working.
                    if (error instanceof ApiError && error.status !== undefined) {
                        throw error
                    }
                    // Browser-level fetch failure (offline, CORS preflight, aborted
                    // navigation). `handleFetch` has already notified apiStatusLogic with
                    // the raw TypeError so the internet-connection banner fires via its
                    // `error?.message === 'Failed to fetch'` check. We re-throw a tagged
                    // ApiError so `loadRecordingMetaFailure` sees a clean errorObject and
                    // error tracking surfaces one handled issue instead of a raw
                    // "TypeError: Failed to fetch" per failed load. The `status: 0`
                    // sentinel distinguishes this from real HTTP responses.
                    apiStatusLogic.findMounted()?.actions.onApiResponse(undefined, error)
                    throw new ApiError('Failed to load recording metadata (network error)', 0, undefined, {
                        code: 'network_error',
                    })
                }
            },
        },
    })),
    listeners(({ values, actions }) => ({
        loadRecordingFromFile: ({ recording }: { recording: ExportedSessionRecordingFileV2['data'] }) => {
            const { id, snapshots, person } = recording
            actions.setSnapshots(snapshots)
            actions.loadRecordingMetaSuccess({
                id,
                viewed: false,
                viewers: [],
                recording_duration: snapshots[snapshots.length - 1].timestamp - snapshots[0].timestamp,
                person: person || undefined,
                start_time: dayjs(snapshots[0].timestamp).toISOString(),
                end_time: dayjs(snapshots[snapshots.length - 1].timestamp).toISOString(),
                snapshot_source: 'unknown',
                expiry_time: undefined,
                recording_ttl: undefined,
            })
        },

        maybeLoadRecordingMeta: () => {
            if (!values.sessionPlayerMetaDataLoading) {
                actions.loadRecordingMeta()
            }
        },
    })),
])

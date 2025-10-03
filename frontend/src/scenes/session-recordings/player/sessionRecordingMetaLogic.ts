import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { snapshotDataLogic } from 'scenes/session-recordings/player/snapshotDataLogic'
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
        return {
            actions: [
                snapshotLogic,
                [
                    'loadSnapshots',
                    'loadSnapshotSources',
                    'loadNextSnapshotSource',
                    'loadSnapshotsForSourceSuccess',
                    'setSnapshots',
                ],
            ],
            values: [
                teamLogic,
                ['currentTeam'],
                annotationsModel,
                ['annotations', 'annotationsLoading'],
                snapshotLogic,
                ['snapshotSources', 'snapshotsBySources', 'snapshotsLoading', 'snapshotsLoaded'],
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
        persistRecording: true,
        maybePersistRecording: true,
        setTrackedWindow: (windowId: string | null) => ({ windowId }),
    }),
    reducers(() => ({
        isNotFound: [
            false as boolean,
            {
                loadRecordingMeta: () => false,
                loadRecordingMetaSuccess: () => false,
                loadRecordingMetaFailure: () => true,
            },
        ],
        trackedWindow: [
            null as string | null,
            {
                setTrackedWindow: (_, { windowId }) => windowId,
            },
        ],
    })),
    loaders(({ values, props }) => ({
        sessionPlayerMetaData: {
            loadRecordingMeta: async (_, breakpoint) => {
                if (!props.sessionRecordingId) {
                    return null
                }
                const headers: Record<string, string> = {}
                if (props.accessToken) {
                    headers.Authorization = `Bearer ${props.accessToken}`
                }
                const response = await api.recordings.get(props.sessionRecordingId, {}, headers)
                breakpoint()

                return response
            },

            persistRecording: async (_, breakpoint) => {
                if (!values.sessionPlayerMetaData) {
                    return null
                }
                await breakpoint(100)
                await api.recordings.persist(props.sessionRecordingId)

                return {
                    ...values.sessionPlayerMetaData,
                    storage: 'object_storage_lts',
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
            })
        },

        maybeLoadRecordingMeta: () => {
            if (!values.sessionPlayerMetaDataLoading) {
                actions.loadRecordingMeta()
            }
        },

        maybePersistRecording: () => {
            if (values.sessionPlayerMetaDataLoading) {
                return
            }

            if (values.sessionPlayerMetaData?.storage === 'object_storage') {
                actions.persistRecording()
            }
        },
    })),
    selectors(() => ({})),
])

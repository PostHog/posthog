import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { dayjs } from 'lib/dayjs'
import { waitForDataLogic } from 'scenes/session-recordings/file-playback/sessionRecordingFilePlaybackSceneLogic'
import { deduplicateSnapshots, parseEncodedSnapshots } from 'scenes/session-recordings/player/sessionRecordingDataLogic'

import { exporterViewLogic } from '../exporterViewLogic'
import { ExportedData } from '../types'
import type { embeddedReplayLogicType } from './embeddedReplayLogicType'

export const embeddedReplayLogic = kea<embeddedReplayLogicType>([
    path(() => ['scenes', 'exporter', 'embeddedReplayLogic']),
    connect({
        values: [exporterViewLogic, ['exportedData']],
    }),
    actions({
        loadReplayFromData: (data: any[]) => ({ data }),
    }),
    selectors(() => ({
        isEmbeddedRecording: [
            (s) => [s.exportedData],
            (exportedData: ExportedData): boolean => !!(exportedData.recording && exportedData.recording.id === ''),
        ],
    })),

    listeners(() => ({
        loadReplayFromData: async ({ data }) => {
            const dataLogic = await waitForDataLogic('exporter')
            if (!dataLogic || !data) {
                return
            }

            // Add a window ID to the snapshots so that we can identify them
            data.forEach((snapshot: any) => {
                snapshot.window_id = 'window-1'
            })

            const snapshots = deduplicateSnapshots(await parseEncodedSnapshots(data, 'embedded'))
            // Simulate a loaded source and sources so that nothing extra gets loaded
            dataLogic.actions.loadSnapshotsForSourceSuccess({
                snapshots: snapshots,
                untransformed_snapshots: snapshots,
                source: { source: 'file' },
            })
            dataLogic.actions.loadSnapshotSourcesSuccess([{ source: 'file' }])
            dataLogic.actions.loadRecordingMetaSuccess({
                id: 'embedded',
                viewed: false,
                recording_duration: snapshots[snapshots.length - 1].timestamp - snapshots[0].timestamp,
                person: undefined,
                start_time: dayjs(snapshots[0].timestamp).toISOString(),
                end_time: dayjs(snapshots[snapshots.length - 1].timestamp).toISOString(),
                snapshot_source: 'unknown', // TODO: we should be able to detect this from the file
            })
        },
    })),

    afterMount(({ values, actions }) => {
        if (values.isEmbeddedRecording) {
            window.addEventListener('message', (event) => {
                if (event.data.type === 'session-replay-data') {
                    actions.loadReplayFromData(event.data.snapshots)
                    return
                }
            })
        }
    }),
])

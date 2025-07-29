import { lemonToast } from '@posthog/lemon-ui'
import { BuiltLogic, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { sessionRecordingDataLogic } from '../player/sessionRecordingDataLogic'
import type { sessionRecordingDataLogicType } from '../player/sessionRecordingDataLogicType'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import type { sessionRecordingFilePlaybackSceneLogicType } from './sessionRecordingFilePlaybackSceneLogicType'
import { ExportedSessionRecordingFileV1, ExportedSessionRecordingFileV2 } from './types'

export const parseExportedSessionRecording = (fileData: string): ExportedSessionRecordingFileV2 => {
    const data = JSON.parse(fileData) as ExportedSessionRecordingFileV1 | ExportedSessionRecordingFileV2

    if (!data.version || !data.data) {
        throw new Error('File does not appear to be a valid session recording export')
    }

    if (data.version === '2023-04-28') {
        return data
    } else if (data.version === '2022-12-02') {
        return {
            version: '2023-04-28',
            data: {
                id: '', // This wasn't available in a previous version
                person: data.data.person || undefined,
                snapshots: Object.entries(data.data.snapshotsByWindowId)
                    .flatMap(([windowId, snapshots]) => {
                        return snapshots.map((snapshot) => ({
                            ...snapshot,
                            windowId,
                        }))
                    })
                    .sort((a, b) => a.timestamp - b.timestamp),
            },
        }
    }
    throw new Error('File version is not supported')
}

/**
 * There's a race between loading the file causing the React component to be rendered that mounts the dataLogic
 * and this logic loading the file and wanting to tell the logic about it
 *
 * This method waits for the dataLogic to be mounted and returns it
 *
 * in practice, it will only wait for 1-2 retries,
 * but a timeout is provided to avoid waiting forever when something breaks
 */
const waitForDataLogic = async (playerKey: string): Promise<BuiltLogic<sessionRecordingDataLogicType>> => {
    const maxRetries = 20 // 2 seconds / 100 ms per retry
    let retries = 0
    let dataLogic = null

    while (retries < maxRetries) {
        dataLogic = sessionRecordingDataLogic.findMounted({
            sessionRecordingId: '',
            playerKey: playerKey,
        })

        if (dataLogic !== null) {
            return dataLogic
        }

        // Wait for a short period before trying again
        await new Promise((resolve) => setTimeout(resolve, 1))
        retries++
    }

    throw new Error('Timeout reached: dataLogic is still null after 2 seconds')
}

export const sessionRecordingFilePlaybackSceneLogic = kea<sessionRecordingFilePlaybackSceneLogicType>([
    path(['scenes', 'session-recordings', 'detail', 'sessionRecordingFilePlaybackSceneLogic']),
    connect(() => ({
        actions: [sessionRecordingEventUsageLogic, ['reportRecordingLoadedFromFile']],
        values: [featureFlagLogic, ['featureFlags']],
    })),

    loaders(({ actions }) => ({
        sessionRecording: {
            __default: null as ExportedSessionRecordingFileV2['data'] | null,
            loadFromFile: async (file: File) => {
                try {
                    const loadedFile: string = await new Promise((resolve, reject) => {
                        const filereader = new FileReader()
                        filereader.onload = (e) => {
                            resolve(e.target?.result as string)
                        }
                        filereader.onerror = (e) => {
                            reject(e)
                        }
                        filereader.readAsText(file)
                    })

                    const data = parseExportedSessionRecording(loadedFile)

                    actions.reportRecordingLoadedFromFile({ success: true })
                    return data.data
                } catch (error) {
                    actions.reportRecordingLoadedFromFile({ success: false, error: `${error}` })
                    lemonToast.error(`File import failed: ${error}`)
                    return null
                }
            },

            resetSessionRecording: () => null,
        },
    })),

    reducers({
        playerKey: [
            'file-playback',
            {
                loadFromFileSuccess: () => `file-playback-${uuid()}`,
                resetSessionRecording: () => 'file-playback',
            },
        ],
    }),

    listeners(({ values }) => ({
        loadFromFileSuccess: async () => {
            const dataLogic = await waitForDataLogic(values.playerKey)

            if (!dataLogic || !values.sessionRecording) {
                return
            }

            const snapshots = values.sessionRecording.snapshots

            // Simulate a loaded source and sources so that nothing extra gets loaded
            dataLogic.cache.snapshotsBySource = {
                'file-file': {
                    snapshots: snapshots,
                    source: { source: 'file' },
                },
            }
            dataLogic.actions.loadSnapshotsForSourceSuccess({
                source: { source: 'file' },
            })
            dataLogic.actions.loadSnapshotSourcesSuccess([{ source: 'file' }])

            dataLogic.actions.loadRecordingMetaSuccess({
                id: values.sessionRecording.id,
                viewed: false,
                viewers: [],
                recording_duration: snapshots[snapshots.length - 1].timestamp - snapshots[0].timestamp,
                person: values.sessionRecording.person || undefined,
                start_time: dayjs(snapshots[0].timestamp).toISOString(),
                end_time: dayjs(snapshots[snapshots.length - 1].timestamp).toISOString(),
                snapshot_source: 'unknown', // TODO: we should be able to detect this from the file
            })
        },
    })),

    beforeUnload(({ values, actions }) => ({
        enabled: () => !!values.sessionRecording,
        message: 'The loaded session recording will be lost. Are you sure you want to leave?',
        onConfirm: () => {
            actions.resetSessionRecording()
        },
    })),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Replay,
                    name: 'Replay',
                    path: urls.replay(),
                },
                {
                    key: Scene.ReplayFilePlayback,
                    name: 'File playback',
                    path: urls.replayFilePlayback(),
                },
            ],
        ],
    }),
])

import { BuiltLogic, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { Breadcrumb, PersonType, RecordingSnapshot } from '~/types'
import { urls } from 'scenes/urls'
import { loaders } from 'kea-loaders'

import { beforeUnload } from 'kea-router'
import { lemonToast } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { uuid } from 'lib/utils'

import type { sessionRecordingFilePlaybackLogicType } from './sessionRecordingFilePlaybackLogicType'
import { eventWithTime } from '@rrweb/types'
import type { sessionRecordingDataLogicType } from '../player/sessionRecordingDataLogicType'
import { sessionRecordingDataLogic } from '../player/sessionRecordingDataLogic'
import { dayjs } from 'lib/dayjs'

export type ExportedSessionRecordingFileV1 = {
    version: '2022-12-02'
    data: {
        person: PersonType | null
        snapshotsByWindowId: Record<string, eventWithTime[]>
    }
}

export type ExportedSessionRecordingFileV2 = {
    version: '2023-04-28'
    data: {
        person: PersonType | null
        snapshots: RecordingSnapshot[]
    }
}

export const createExportedSessionRecording = (
    logic: BuiltLogic<sessionRecordingDataLogicType>
): ExportedSessionRecordingFileV2 => {
    const { sessionPlayerMetaData, sessionPlayerSnapshotData } = logic.values

    return {
        version: '2023-04-28',
        data: {
            person: sessionPlayerMetaData.person,
            snapshots: sessionPlayerSnapshotData?.snapshots || [],
        },
    }
}

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
                person: data.data.person,
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
    } else {
        throw new Error('File version is not supported')
    }
}

export const sessionRecordingFilePlaybackLogic = kea<sessionRecordingFilePlaybackLogicType>([
    path(['scenes', 'session-recordings', 'detail', 'sessionRecordingDetailLogic']),
    connect({
        actions: [eventUsageLogic, ['reportRecordingLoadedFromFile']],
    }),

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
        loadFromFileSuccess: () => {
            // Once we loaded the file we set the logic
            const dataLogic = sessionRecordingDataLogic.findMounted({
                sessionRecordingId: '',
                playerKey: values.playerKey,
            })

            if (!dataLogic || !values.sessionRecording) {
                return
            }

            console.log(values.sessionRecording)
            const snapshots = values.sessionRecording.snapshots

            dataLogic.actions.loadRecordingSnapshotsSuccess({
                snapshots,
            })

            console.log({
                person: values.sessionRecording.person,
                start: dayjs(snapshots[0].timestamp),
                end: dayjs(snapshots[snapshots.length - 1].timestamp),
                pinnedCount: 0,
                // TODO: Remove this once we are sold on new segments logic
                segments: [],
            })

            dataLogic.actions.loadRecordingMetaSuccess({
                person: values.sessionRecording.person,
                start: dayjs(snapshots[0].timestamp),
                end: dayjs(snapshots[snapshots.length - 1].timestamp),
                pinnedCount: 0,
                // TODO: Remove this once we are sold on new segments logic
                segments: [],
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
                    name: `Recordings`,
                    path: urls.sessionRecordings(),
                },
                {
                    name: 'Import',
                },
            ],
        ],
    }),
])

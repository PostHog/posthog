import { MakeLogicType, BuiltLogic, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'
import { createWindowIdRegistry } from '@posthog/replay-shared'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { RecordingSnapshot } from '../../../../../common/replay-shared/src/types'
import type { FeatureFlagsSet } from '../../../lib/logic/featureFlagLogic'
import type { PersonType } from '../../../types'
import {
    sessionRecordingDataCoordinatorLogic,
    type sessionRecordingDataCoordinatorLogicType,
} from '../player/sessionRecordingDataCoordinatorLogic'
import { SessionRecordingPlayerProps } from '../player/SessionRecordingPlayer'
import { parseEncodedSnapshots } from '../player/snapshot-processing/process-all-snapshots'
import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import {
    ExportedSessionRecordingFileRawHeader,
    ExportedViewport,
    ExportedSessionRecordingFileV1,
    ExportedSessionRecordingFileV2,
    LoadedSessionRecordingFile,
} from './types'

const RAW_EXPORT_MAGIC = new TextEncoder().encode('PHREC1\n')
// One parse call joins its decompressed blocks into one string, so a whole large session would pass the browser's string length limit.
const RAW_EXPORT_BLOCKS_PER_PARSE = 50

export const isRawExportedSessionRecording = (bytes: Uint8Array): boolean =>
    bytes.byteLength >= RAW_EXPORT_MAGIC.byteLength && RAW_EXPORT_MAGIC.every((byte, i) => bytes[i] === byte)

export const parseRawExportedSessionRecording = async (bytes: Uint8Array): Promise<LoadedSessionRecordingFile> => {
    const headerEnd = bytes.indexOf(0x0a, RAW_EXPORT_MAGIC.byteLength)
    if (headerEnd === -1) {
        throw new Error('File does not have a valid header')
    }
    const header: ExportedSessionRecordingFileRawHeader = JSON.parse(
        new TextDecoder().decode(bytes.subarray(RAW_EXPORT_MAGIC.byteLength, headerEnd))
    )
    if (header.version !== '2026-11-raw') {
        throw new Error(`Unsupported export version ${header.version}`)
    }

    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    const registerWindowId = createWindowIdRegistry()
    const snapshots: RecordingSnapshot[] = []
    let offset = headerEnd + 1
    let blockCount = 0
    while (offset < bytes.byteLength) {
        const groupStart = offset
        for (let i = 0; i < RAW_EXPORT_BLOCKS_PER_PARSE && offset < bytes.byteLength; i++) {
            if (offset + 4 > bytes.byteLength || offset + 4 + view.getUint32(offset) > bytes.byteLength) {
                throw new Error('File is truncated')
            }
            offset += 4 + view.getUint32(offset)
            blockCount++
        }
        snapshots.push(
            ...(await parseEncodedSnapshots(
                bytes.subarray(groupStart, offset),
                header.session_id,
                undefined,
                registerWindowId
            ))
        )
    }
    if (blockCount !== header.block_count) {
        throw new Error(`File has ${blockCount} blocks but its header lists ${header.block_count}`)
    }
    if (!snapshots.length) {
        throw new Error('File contains no snapshots')
    }

    return {
        id: header.session_id,
        person: header.person,
        snapshots: snapshots.sort((a, b) => a.timestamp - b.timestamp),
        viewports: header.viewports,
    }
}

export const parseExportedSessionRecording = (fileData: string): ExportedSessionRecordingFileV2 => {
    const data = JSON.parse(fileData) as ExportedSessionRecordingFileV1 | ExportedSessionRecordingFileV2

    if (!data.version || !data.data) {
        throw new Error('File does not appear to be a valid session recording export')
    }

    if (data.version === '2023-04-28') {
        // Files exported before window ids became integers carry the window UUID, and the segmenter indexes windows by number
        const registerWindowId = createWindowIdRegistry()
        for (const snapshot of data.data.snapshots) {
            const windowId: number | string = snapshot.windowId
            if (typeof windowId === 'string') {
                snapshot.windowId = registerWindowId(windowId)
            }
        }
        return data
    } else if (data.version === '2022-12-02') {
        const registerWindowId = createWindowIdRegistry()
        return {
            version: '2023-04-28',
            data: {
                id: '',
                person: data.data.person || undefined,
                snapshots: Object.entries(data.data.snapshotsByWindowId)
                    .flatMap(([windowIdUuid, snapshots]) => {
                        const windowId = registerWindowId(windowIdUuid)
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
const waitForDataLogic = async (
    playerProps: SessionRecordingPlayerProps
): Promise<BuiltLogic<sessionRecordingDataCoordinatorLogicType>> => {
    const maxRetries = 20 // 2 seconds / 100 ms per retry
    let retries = 0
    let dataLogic = null

    while (retries < maxRetries) {
        dataLogic = sessionRecordingDataCoordinatorLogic.findMounted({
            sessionRecordingId: playerProps.sessionRecordingId,
            playerKey: playerProps.playerKey,
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

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sessionRecordingFilePlaybackSceneLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    breadcrumbs: Breadcrumb[]
    fileId: string
    playerProps: SessionRecordingPlayerProps
    sessionRecording: LoadedSessionRecordingFile | null
    sessionRecordingLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sessionRecordingFilePlaybackSceneLogicActions {
    reportRecordingLoadedFromFile: (data: { error?: string; success: boolean }) => {
        error?: string | undefined
        success: boolean
    } // sessionRecordingEventUsageLogic
    loadFromFile: (file: File) => File
    loadFromFileFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadFromFileSuccess: (
        sessionRecording: {
            id: string
            person: PersonType | undefined
            snapshots: RecordingSnapshot[]
            viewports?: ExportedViewport[]
        } | null,
        payload?: File
    ) => {
        sessionRecording: {
            id: string
            person: PersonType | undefined
            snapshots: RecordingSnapshot[]
            viewports?: ExportedViewport[]
        } | null
        payload?: File
    }
    resetSessionRecording: () => any
    resetSessionRecordingFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    resetSessionRecordingSuccess: (
        sessionRecording: null,
        payload?: any
    ) => {
        sessionRecording: null
        payload?: any
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sessionRecordingFilePlaybackSceneLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        playerProps: (fileId: string) => SessionRecordingPlayerProps
    }
}

export type sessionRecordingFilePlaybackSceneLogicType = MakeLogicType<
    sessionRecordingFilePlaybackSceneLogicValues,
    sessionRecordingFilePlaybackSceneLogicActions,
    Record<string, any>,
    sessionRecordingFilePlaybackSceneLogicMeta
>

export const sessionRecordingFilePlaybackSceneLogic = kea<sessionRecordingFilePlaybackSceneLogicType>([
    path(['scenes', 'session-recordings', 'detail', 'sessionRecordingFilePlaybackSceneLogic']),
    connect(() => ({
        actions: [sessionRecordingEventUsageLogic, ['reportRecordingLoadedFromFile']],
        values: [featureFlagLogic, ['featureFlags']],
    })),

    loaders(({ actions }) => ({
        sessionRecording: {
            __default: null as LoadedSessionRecordingFile | null,
            loadFromFile: async (file: File) => {
                try {
                    const bytes = new Uint8Array(await file.arrayBuffer())
                    const data = isRawExportedSessionRecording(bytes)
                        ? await parseRawExportedSessionRecording(bytes)
                        : parseExportedSessionRecording(new TextDecoder().decode(bytes)).data
                    actions.reportRecordingLoadedFromFile({ success: true })
                    return data
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
        fileId: [
            'empty' as string,
            {
                loadFromFileSuccess: () => uuid(),
                resetSessionRecording: () => 'empty',
            },
        ],
    }),

    beforeUnload(({ values, actions }) => ({
        enabled: () => !!values.sessionRecording,
        message: 'The loaded session recording will be lost. Are you sure you want to leave?',
        onConfirm: () => {
            actions.resetSessionRecording()
        },
    })),

    selectors({
        playerProps: [
            (s) => [s.fileId],
            (fileId: string) =>
                ({
                    sessionRecordingId: '',
                    playerKey: 'file-playback-' + fileId,
                }) as SessionRecordingPlayerProps,
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Replay,
                    name: 'Replay',
                    path: urls.replay(),
                    iconType: 'session_replay',
                },
                {
                    key: Scene.ReplayFilePlayback,
                    name: 'File playback',
                    path: urls.replayFilePlayback(),
                    iconType: 'session_replay',
                },
            ],
        ],
    }),

    listeners(({ values }) => ({
        loadFromFileSuccess: async () => {
            const recordingDataLogic = await waitForDataLogic(values.playerProps)
            if (!recordingDataLogic || !values.sessionRecording) {
                return
            }
            recordingDataLogic.actions.loadRecordingFromFile(values.sessionRecording)
        },
    })),
])

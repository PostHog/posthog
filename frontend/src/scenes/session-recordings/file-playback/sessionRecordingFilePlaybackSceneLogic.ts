import { MakeLogicType, BuiltLogic, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { beforeUnload } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'
import { ExpansionBudget, ReplayTelemetry, createWindowIdRegistry } from '@posthog/replay-shared'

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
    ExportedSessionRecordingFileV1,
    ExportedSessionRecordingFileV2,
    LoadedSessionRecordingFile,
} from './types'

const RAW_EXPORT_MAGIC = new TextEncoder().encode('PHREC1\n')

// Limits for a file a person opens by hand, so a crafted file cannot exhaust the tab before anything renders.
const MAX_RAW_HEADER_BYTES = 8 * 1024 * 1024
const MAX_RAW_BLOCKS = 100_000
const MAX_RAW_BLOCK_EXPANDED_BYTES = 256 * 1024 * 1024
const MAX_RAW_EXPANDED_BYTES = 1024 * 1024 * 1024

// A raw snappy block starts with its decompressed length as a little-endian base-128 varint.
const snappyExpandedLength = (block: Uint8Array): number => {
    let length = 0
    for (let i = 0; i < Math.min(block.byteLength, 5); i++) {
        length += (block[i] & 0x7f) * 2 ** (7 * i)
        if ((block[i] & 0x80) === 0) {
            return length
        }
    }
    return Infinity
}

export const isRawExportedSessionRecording = (bytes: Uint8Array): boolean =>
    bytes.byteLength >= RAW_EXPORT_MAGIC.byteLength && RAW_EXPORT_MAGIC.every((byte, i) => bytes[i] === byte)

const isFiniteNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)

// The player parses width and height as integers and puts href into the patched meta event.
const isValidViewport = (viewport: unknown): boolean => {
    const { timestamp, width, height, href } = (viewport ?? {}) as Record<string, unknown>
    const isDimension = (value: unknown): boolean => /^\d+$/.test(String(value))
    return isFiniteNumber(timestamp) && isDimension(width) && isDimension(height) && typeof href === 'string'
}

const parseRawHeader = (line: string): ExportedSessionRecordingFileRawHeader => {
    const header = JSON.parse(line)
    if (typeof header !== 'object' || header === null) {
        throw new Error('File does not have a valid header')
    }
    if (header.version !== '2026-11-raw') {
        throw new Error(`Unsupported export version ${header.version}`)
    }
    if (
        typeof header.session_id !== 'string' ||
        !Number.isInteger(header.block_count) ||
        !Array.isArray(header.viewports) ||
        !header.viewports.every(isValidViewport)
    ) {
        throw new Error('File does not have a valid header')
    }
    return header
}

// Event name the shared parser captures when it drops lines it cannot parse.
const UNPARSEABLE_LINES_EVENT = 'session recording had unparseable lines'

export const parseRawExportedSessionRecording = async (
    bytes: Uint8Array,
    onUnreadableLines?: () => void
): Promise<LoadedSessionRecordingFile> => {
    const headerEnd = bytes
        .subarray(0, RAW_EXPORT_MAGIC.byteLength + MAX_RAW_HEADER_BYTES)
        .indexOf(0x0a, RAW_EXPORT_MAGIC.byteLength)
    if (headerEnd === -1) {
        throw new Error('File does not have a valid header')
    }
    const header = parseRawHeader(new TextDecoder().decode(bytes.subarray(RAW_EXPORT_MAGIC.byteLength, headerEnd)))

    // The shared parser stops quietly at a truncated block, so check the framing here first.
    const blocks = bytes.subarray(headerEnd + 1)
    const view = new DataView(blocks.buffer, blocks.byteOffset, blocks.byteLength)
    let blockCount = 0
    let expandedBytes = 0
    for (let offset = 0; offset < blocks.byteLength; blockCount++) {
        const blockEnd = offset + 4 > blocks.byteLength ? Infinity : offset + 4 + view.getUint32(offset)
        if (blockEnd > blocks.byteLength) {
            throw new Error('File is truncated')
        }
        // The shared parser reads a zero length at the start as unframed data.
        if (blockEnd === offset + 4) {
            throw new Error('File has an empty block')
        }
        const blockExpandedBytes = snappyExpandedLength(blocks.subarray(offset + 4, blockEnd))
        expandedBytes += blockExpandedBytes
        if (blockExpandedBytes > MAX_RAW_BLOCK_EXPANDED_BYTES || expandedBytes > MAX_RAW_EXPANDED_BYTES) {
            throw new Error('File is too large to play back in the browser')
        }
        offset = blockEnd
        if (blockCount >= MAX_RAW_BLOCKS) {
            throw new Error('File is too large to play back in the browser')
        }
    }
    if (blockCount !== header.block_count) {
        throw new Error(`File has ${blockCount} blocks but its header lists ${header.block_count}`)
    }
    // The shared parser's telemetry would send unreadable lines, which hold page content, to analytics.
    const telemetry: ReplayTelemetry = {
        capture: (event) => {
            if (event === UNPARSEABLE_LINES_EVENT) {
                onUnreadableLines?.()
            }
        },
        captureException: () => {},
    }
    // Nested compressed fields share the room left after the blocks themselves.
    const budget = new ExpansionBudget(MAX_RAW_EXPANDED_BYTES - expandedBytes)
    const snapshots = await parseEncodedSnapshots(blocks, header.session_id, undefined, undefined, telemetry, budget)
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
        } | null,
        payload?: File
    ) => {
        sessionRecording: {
            id: string
            person: PersonType | undefined
            snapshots: RecordingSnapshot[]
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
                        ? await parseRawExportedSessionRecording(bytes, () =>
                              lemonToast.warning(
                                  "Part of this recording couldn't be read, so playback may be incomplete. The file may be damaged."
                              )
                          )
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

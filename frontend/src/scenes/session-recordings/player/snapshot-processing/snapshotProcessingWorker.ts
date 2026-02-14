import { decompress_raw } from 'snappy-wasm'
import snappyInit from 'snappy-wasm'

import { RecordingSnapshot } from '~/types'

import { createWindowIdRegistry, isLengthPrefixedSnappy, processSnapshotLine } from './snapshot-parsing-utils'
import type {
    SnapshotProcessingRequest,
    SnapshotProcessingResponse,
    WindowIdMapping,
} from './snapshot-processing-types'
import { toEventWithTime } from './to-event-with-time'

let snappyInitPromise: Promise<unknown> | null = null

async function initSnappy(): Promise<void> {
    if (!snappyInitPromise) {
        snappyInitPromise = snappyInit()
    }
    await snappyInitPromise
}

function decompressLengthPrefixed(uint8Data: Uint8Array): Uint8Array[] {
    const blocks: Uint8Array[] = []
    let offset = 0

    while (offset < uint8Data.byteLength) {
        if (offset + 4 > uint8Data.byteLength) {
            break
        }

        const length =
            ((uint8Data[offset] << 24) |
                (uint8Data[offset + 1] << 16) |
                (uint8Data[offset + 2] << 8) |
                uint8Data[offset + 3]) >>>
            0
        offset += 4

        if (offset + length > uint8Data.byteLength) {
            break
        }

        const decompressed = decompress_raw(uint8Data.slice(offset, offset + length))
        blocks.push(decompressed)
        offset += length
    }

    return blocks
}

function decompressToText(compressedData: Uint8Array): { text: string; compressionType: string } {
    const textDecoder = new TextDecoder('utf-8')

    if (isLengthPrefixedSnappy(compressedData)) {
        const blocks = decompressLengthPrefixed(compressedData)
        return {
            text: blocks.map((block) => textDecoder.decode(block)).join('\n'),
            compressionType: 'length_prefixed_snappy',
        }
    }

    try {
        const decompressed = decompress_raw(compressedData)
        return { text: textDecoder.decode(decompressed), compressionType: 'raw_snappy' }
    } catch {
        return { text: textDecoder.decode(compressedData), compressionType: 'uncompressed' }
    }
}

function parseLines(
    lines: string[],
    sessionId: string,
    registerWindowId: (uuid: string) => number
): RecordingSnapshot[] {
    const snapshots: RecordingSnapshot[] = []

    for (const line of lines) {
        if (!line) {
            continue
        }
        try {
            const parsed = JSON.parse(line) as unknown
            snapshots.push(...processSnapshotLine(parsed, sessionId, registerWindowId, (d) => toEventWithTime(d)))
        } catch {
            // unparseable lines are skipped
        }
    }

    return snapshots
}

async function processCompressedData(
    compressedData: Uint8Array,
    sessionId: string
): Promise<{
    snapshots: RecordingSnapshot[]
    windowIdMappings: WindowIdMapping[]
    metrics: SnapshotProcessingResponse['metrics']
}> {
    const startTime = performance.now()

    await initSnappy()
    const decompressStart = performance.now()

    const { text: decompressedText, compressionType } = decompressToText(compressedData)
    const decompressDurationMs = performance.now() - decompressStart

    const lines = decompressedText.split('\n').filter((line) => line.trim().length > 0)

    const windowIdMappings: WindowIdMapping[] = []
    const registerWindowId = createWindowIdRegistry((uuid, index) => {
        windowIdMappings.push({ uuid, index })
    })

    const snapshots = parseLines(lines, sessionId, registerWindowId)
    const parseDurationMs = performance.now() - startTime

    return {
        snapshots,
        windowIdMappings,
        metrics: {
            decompressDurationMs,
            parseDurationMs,
            snapshotCount: snapshots.length,
            lineCount: lines.length,
            compressionType,
        },
    }
}

self.addEventListener('message', async (event: MessageEvent<SnapshotProcessingRequest>) => {
    const { id, compressedData, sessionId } = event.data

    try {
        const result = await processCompressedData(compressedData, sessionId)

        const response: SnapshotProcessingResponse = {
            id,
            snapshots: result.snapshots,
            windowIdMappings: result.windowIdMappings,
            metrics: result.metrics,
        }
        self.postMessage(response)
    } catch (error) {
        const response: SnapshotProcessingResponse = {
            id,
            snapshots: null,
            windowIdMappings: [],
            error: error instanceof Error ? error.message : 'Unknown error',
        }
        self.postMessage(response)
    }
})

self.postMessage({ type: 'ready' })

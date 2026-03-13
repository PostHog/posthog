import { noOpTelemetry, ReplayTelemetry } from '../telemetry'
import { EncodedRecordingSnapshot, RecordingSnapshot } from '../types'
import { parseJsonSnapshots, createWindowIdRegistry, RegisterWindowIdCallback } from './process-all-snapshots'

export type SnappyDecompressor = (block: Uint8Array) => Promise<Uint8Array>

function isLengthPrefixedSnappy(uint8Data: Uint8Array): boolean {
    if (uint8Data.byteLength < 4) {
        return false
    }

    const firstLength = ((uint8Data[0] << 24) | (uint8Data[1] << 16) | (uint8Data[2] << 8) | uint8Data[3]) >>> 0

    if (firstLength === 0 || firstLength > uint8Data.byteLength) {
        return false
    }

    if (4 + firstLength > uint8Data.byteLength) {
        return false
    }

    return true
}

function extractLengthPrefixedBlocks(uint8Data: Uint8Array): Uint8Array[] {
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

        blocks.push(uint8Data.slice(offset, offset + length))
        offset += length
    }

    return blocks
}

const DECOMPRESSION_BATCH_SIZE = 10

async function decompressBlocks(blocks: Uint8Array[], decompressor: SnappyDecompressor): Promise<string> {
    const decompressedBlocks: Uint8Array[] = []

    for (let i = 0; i < blocks.length; i += DECOMPRESSION_BATCH_SIZE) {
        const batch = blocks.slice(i, i + DECOMPRESSION_BATCH_SIZE)
        const results = await Promise.all(batch.map((block) => decompressor(block)))
        decompressedBlocks.push(...results)
        if (i + DECOMPRESSION_BATCH_SIZE < blocks.length) {
            await new Promise<void>((r) => setTimeout(r, 0))
        }
    }

    const textDecoder = new TextDecoder('utf-8')
    return decompressedBlocks.map((data) => textDecoder.decode(data)).join('\n')
}

function splitLines(text: string): string[] {
    return text.split('\n').filter((line) => line.trim().length > 0)
}

export const parseEncodedSnapshots = async (
    items: (RecordingSnapshot | EncodedRecordingSnapshot | string)[] | ArrayBuffer | Uint8Array,
    sessionId: string,
    telemetry: ReplayTelemetry = noOpTelemetry,
    registerWindowId?: RegisterWindowIdCallback,
    decompressor?: SnappyDecompressor
): Promise<RecordingSnapshot[]> => {
    const startTime = performance.now()
    const registerFn: RegisterWindowIdCallback = registerWindowId || createWindowIdRegistry()

    if (items instanceof ArrayBuffer || items instanceof Uint8Array) {
        const uint8Data = items instanceof Uint8Array ? items : new Uint8Array(items)

        if (!decompressor) {
            const textDecoder = new TextDecoder('utf-8')
            const text = textDecoder.decode(uint8Data)
            return parseJsonSnapshots(splitLines(text), sessionId, telemetry, registerFn)
        }

        if (isLengthPrefixedSnappy(uint8Data)) {
            try {
                const blocks = extractLengthPrefixedBlocks(uint8Data)
                const text = await decompressBlocks(blocks, decompressor)
                const lines = splitLines(text)
                const snapshots = await parseEncodedSnapshots(lines, sessionId, telemetry, registerFn)
                telemetry.capture('replay_parse_timing', {
                    snapshot_count: snapshots.length,
                    parse_duration_ms: performance.now() - startTime,
                    line_count: lines.length,
                    compression_type: 'length_prefixed_snappy',
                })
                return snapshots
            } catch (error) {
                telemetry.captureException(new Error('Failed to decompress length-prefixed snapshot data'), {
                    sessionId,
                    error: error instanceof Error ? error.message : 'Unknown error',
                    feature: 'session-recording-client-side-decompression',
                })
                return []
            }
        }

        try {
            const decompressedData = await decompressor(uint8Data)
            const textDecoder = new TextDecoder('utf-8')
            const text = textDecoder.decode(decompressedData)
            const lines = splitLines(text)
            const snapshots = await parseEncodedSnapshots(lines, sessionId, telemetry, registerFn)
            telemetry.capture('replay_parse_timing', {
                snapshot_count: snapshots.length,
                parse_duration_ms: performance.now() - startTime,
                line_count: lines.length,
                compression_type: 'raw_snappy',
            })
            return snapshots
        } catch (error) {
            try {
                const textDecoder = new TextDecoder('utf-8')
                const text = textDecoder.decode(uint8Data)
                return parseEncodedSnapshots(splitLines(text), sessionId, telemetry, registerFn)
            } catch (decodeError) {
                telemetry.captureException(new Error('Failed to process snapshot data'), {
                    sessionId,
                    decompressionError: error instanceof Error ? error.message : 'Unknown error',
                    decodeError: decodeError instanceof Error ? decodeError.message : 'Unknown error',
                    feature: 'session-recording-client-side-decompression',
                })
                return []
            }
        }
    }

    return parseJsonSnapshots(items, sessionId, telemetry, registerFn)
}

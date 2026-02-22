import { eventWithTime } from '@posthog/rrweb-types'

import { RecordingSnapshot } from '~/types'

import { chunkMutationSnapshot } from './chunk-large-mutations'

export type RegisterWindowIdCallback = (uuid: string) => number
export type CoerceFunction = (d: unknown, sessionId: string) => eventWithTime

export function createWindowIdRegistry(onNewId?: (uuid: string, index: number) => void): RegisterWindowIdCallback {
    const uuidToIndex: Record<string, number> = {}
    return (uuid: string): number => {
        if (uuid in uuidToIndex) {
            return uuidToIndex[uuid]
        }
        const index = Object.keys(uuidToIndex).length + 1
        uuidToIndex[uuid] = index
        onNewId?.(uuid, index)
        return index
    }
}

export function isLengthPrefixedSnappy(uint8Data: Uint8Array): boolean {
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

export function isRecordingSnapshot(x: unknown): x is RecordingSnapshot {
    return (
        typeof x === 'object' &&
        x !== null &&
        'type' in x &&
        'timestamp' in x &&
        'windowId' in x &&
        typeof (x as RecordingSnapshot).windowId === 'number'
    )
}

export function processSnapshotLine(
    parsed: unknown,
    sessionId: string,
    registerWindowId: RegisterWindowIdCallback,
    coerce: CoerceFunction
): RecordingSnapshot[] {
    if (Array.isArray(parsed)) {
        parsed = { windowId: parsed[0], data: [parsed[1]] }
    }

    if (isRecordingSnapshot(parsed)) {
        const snap = coerce(parsed, sessionId)
        return chunkMutationSnapshot({ windowId: parsed.windowId, ...snap })
    }

    const line = parsed as Record<string, any>

    if ('type' in line && 'timestamp' in line && typeof line['windowId'] === 'string') {
        const windowId = registerWindowId(line['windowId'])
        const snap = coerce(line, sessionId)
        return chunkMutationSnapshot({ windowId, ...snap })
    }

    const snapshotData = line['data'] || []
    const rawWindowId: string = line['window_id'] || line['windowId'] || ''
    const windowId = registerWindowId(rawWindowId)

    const results: RecordingSnapshot[] = []
    for (const d of snapshotData) {
        const snap = coerce(d, sessionId)
        results.push(...chunkMutationSnapshot({ windowId, ...snap }))
    }
    return results
}

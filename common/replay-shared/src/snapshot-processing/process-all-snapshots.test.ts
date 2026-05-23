import { EventType } from '@posthog/rrweb-types'

import { ReplayTelemetry } from '../telemetry'
import {
    RecordingSnapshot,
    SessionRecordingSnapshotSource,
    SessionRecordingSnapshotSourceResponse,
    SnapshotSourceType,
} from '../types'
import { processAllSnapshots, ProcessingCache } from './process-all-snapshots'
import { keyForSource } from './source-key'
import { clearThrottle } from './throttle-capturing'

function buildTelemetry(): { telemetry: ReplayTelemetry; captures: { event: string; props?: Record<string, unknown> }[] } {
    const captures: { event: string; props?: Record<string, unknown> }[] = []
    const telemetry: ReplayTelemetry = {
        capture: (event, props) => {
            captures.push({ event, props })
        },
        captureException: () => {},
    }
    return { telemetry, captures }
}

describe('processAllSnapshots malformed full snapshots', () => {
    const source: SessionRecordingSnapshotSource = { source: SnapshotSourceType.blob_v2, blob_key: '0' }
    const sourceKey = keyForSource(source)
    const viewportForTimestamp = (): undefined => undefined

    beforeEach(() => {
        clearThrottle()
    })

    it('skips a FullSnapshot whose data is undefined and emits malformed-full-snapshot telemetry', async () => {
        const malformed = {
            type: EventType.FullSnapshot,
            timestamp: 1000,
            windowId: 1,
            data: undefined,
        } as unknown as RecordingSnapshot

        const snapshotsBySource: Record<string, SessionRecordingSnapshotSourceResponse> = {
            [sourceKey]: { snapshots: [malformed] },
        }
        const cache: ProcessingCache = { snapshots: {} }
        const { telemetry, captures } = buildTelemetry()

        const result = await processAllSnapshots(
            [source],
            snapshotsBySource,
            cache,
            viewportForTimestamp,
            'session-malformed-data',
            telemetry
        )

        expect(result).toEqual([])
        expect(captures.some((c) => c.event === 'malformed full snapshot')).toBe(true)
    })

    it('skips a FullSnapshot whose data.node is undefined and emits malformed-full-snapshot telemetry', async () => {
        const malformed = {
            type: EventType.FullSnapshot,
            timestamp: 2000,
            windowId: 1,
            data: { initialOffset: { top: 0, left: 0 } },
        } as unknown as RecordingSnapshot

        const snapshotsBySource: Record<string, SessionRecordingSnapshotSourceResponse> = {
            [sourceKey]: { snapshots: [malformed] },
        }
        const cache: ProcessingCache = { snapshots: {} }
        const { telemetry, captures } = buildTelemetry()

        const result = await processAllSnapshots(
            [source],
            snapshotsBySource,
            cache,
            viewportForTimestamp,
            'session-malformed-node',
            telemetry
        )

        expect(result).toEqual([])
        expect(captures.some((c) => c.event === 'malformed full snapshot')).toBe(true)
    })

    it('keeps surrounding well-formed snapshots when one malformed FullSnapshot is in the middle', async () => {
        const goodMeta: RecordingSnapshot = {
            type: EventType.Meta,
            timestamp: 500,
            windowId: 1,
            data: { width: 1024, height: 768, href: 'https://example.com' },
        } as unknown as RecordingSnapshot
        const malformed = {
            type: EventType.FullSnapshot,
            timestamp: 1000,
            windowId: 1,
            data: undefined,
        } as unknown as RecordingSnapshot
        const goodIncremental: RecordingSnapshot = {
            type: EventType.IncrementalSnapshot,
            timestamp: 1500,
            windowId: 1,
            data: { source: 1, positions: [] },
        } as unknown as RecordingSnapshot

        const snapshotsBySource: Record<string, SessionRecordingSnapshotSourceResponse> = {
            [sourceKey]: { snapshots: [goodMeta, malformed, goodIncremental] },
        }
        const cache: ProcessingCache = { snapshots: {} }
        const { telemetry } = buildTelemetry()

        const result = await processAllSnapshots(
            [source],
            snapshotsBySource,
            cache,
            viewportForTimestamp,
            'session-mixed',
            telemetry
        )

        expect(result.map((s) => s.timestamp)).toEqual([500, 1500])
        expect(result.find((s) => s.type === EventType.FullSnapshot)).toBeUndefined()
    })
})

import { EventType, IncrementalSource } from '@posthog/rrweb-types'
import { ViewportResolution } from 'scenes/session-recordings/player/snapshot-processing/patch-meta-event'

import { RecordingSnapshot, SnapshotSourceType } from '~/types'

import { processAllSnapshots } from './process-all-snapshots'

const alwaysOneGenerator = (): number => 1
const alwaysTwoGenerator = (): number => 2
const rotateIdsBetween = (start: number, end: number): (() => number) => {
    let current = start
    return () => {
        const result = current
        current = (current + 1) % end
        return result
    }
}

describe('processAllSnapshots throttling', () => {
    const createAdds = (nodeIdGenerator: () => number, repeats: number = 1): any[] => {
        const adds = []
        for (let i = 0; i < repeats; i++) {
            adds.push({ id: i, node: { id: nodeIdGenerator(), type: 2, tagName: 'div' } })
        }
        return adds
    }

    const createRemoves = (nodeIdGenerator: () => number, repeats: number = 1): any[] => {
        const removes = []
        for (let i = 0; i < repeats; i++) {
            removes.push({ id: nodeIdGenerator(), parentId: 0 })
        }
        return removes
    }

    const createTexts = (nodeIdGenerator: () => number, repeats: number = 1): any[] => {
        const texts = []
        for (let i = 0; i < repeats; i++) {
            texts.push({ id: nodeIdGenerator(), value: 'text' + i })
        }
        return texts
    }

    const createAttributes = (nodeIdGenerator: () => number, repeats: number = 1): any[] => {
        const attributes = []
        for (let i = 0; i < repeats; i++) {
            attributes.push({ id: nodeIdGenerator(), attributes: { class: 'test' + i } })
        }
        return attributes
    }

    const createIncrementalSnapshot = (
        timestamp: number,
        mutations: {
            adds?: any[]
            removes?: any[]
            texts?: any[]
            attributes?: any[]
        } = {},
        repeats: number = 1
    ): RecordingSnapshot[] => {
        const snapshots: RecordingSnapshot[] = []
        for (let i = 0; i < repeats; i++) {
            snapshots.push({
                type: EventType.IncrementalSnapshot,
                timestamp: timestamp + i,
                windowId: '1',
                data: {
                    source: IncrementalSource.Mutation,
                    adds: mutations.adds || [],
                    removes: mutations.removes || [],
                    texts: mutations.texts || [],
                    attributes: mutations.attributes || [],
                },
            })
        }
        return snapshots
    }

    const createFullSnapshot = (timestamp: number): RecordingSnapshot => ({
        type: EventType.FullSnapshot,
        timestamp,
        windowId: '1',
        data: {
            node: {
                id: 1,
                type: 0,
                childNodes: [],
            },
            initialOffset: { top: 0, left: 0 },
        },
    })

    const fakeViewportForTimestamp = (): ViewportResolution | undefined => {
        return {
            width: '1920',
            height: '1080',
            href: 'https://example.com',
        }
    }

    const callProcessing = (snapshots: RecordingSnapshot[]): RecordingSnapshot[] => {
        return processAllSnapshots(
            [
                {
                    source: 'blob',
                    start_timestamp: '2025-05-14T15:37:18.897000Z',
                    end_timestamp: '2025-05-14T15:42:18.378000Z',
                    blob_key: '1',
                },
            ],
            { 'blob-1': { source: { source: SnapshotSourceType.blob_v2, blob_key: 'blob-1' }, snapshots } },
            fakeViewportForTimestamp,
            '12345'
        )
    }

    it('processes all mutations without throttling', () => {
        // Create a sequence of rapid mutations for the same node
        const snapshots: RecordingSnapshot[] = [
            createFullSnapshot(1000),
            ...createIncrementalSnapshot(1001, {
                adds: createAdds(alwaysOneGenerator),
            }),
            ...createIncrementalSnapshot(1002, {
                texts: createTexts(alwaysOneGenerator),
            }),
            ...createIncrementalSnapshot(1003, {
                texts: createTexts(alwaysOneGenerator),
            }),
            ...createIncrementalSnapshot(1004, {
                texts: createTexts(alwaysOneGenerator),
            }),
            ...createIncrementalSnapshot(1005, {
                attributes: createAttributes(alwaysOneGenerator),
            }),
            ...createIncrementalSnapshot(1006, {
                removes: createRemoves(alwaysOneGenerator),
            }),
        ]

        const result = callProcessing(snapshots)

        // Verify all mutations are processed
        expect(result.filter((s) => s.type === EventType.IncrementalSnapshot)).toHaveLength(6)

        // Verify order is preserved
        const incrementalSnapshots = result.filter((s) => s.type === EventType.IncrementalSnapshot)
        expect(incrementalSnapshots[0].timestamp).toBe(1001)
        expect(incrementalSnapshots[1].timestamp).toBe(1002)
        expect(incrementalSnapshots[2].timestamp).toBe(1003)
        expect(incrementalSnapshots[3].timestamp).toBe(1004)
        expect(incrementalSnapshots[4].timestamp).toBe(1005)
        expect(incrementalSnapshots[5].timestamp).toBe(1006)
    })

    describe('just repeated adds', () => {
        it('does not throttle adds when low enough load is spread between nodes', () => {
            // Create a sequence of rapid mutations for the same node
            const snapshots: RecordingSnapshot[] = [
                createFullSnapshot(1000),
                ...createIncrementalSnapshot(1001, {
                    adds: createAdds(rotateIdsBetween(0, 1000), 5_000),
                }),
            ]

            const result = callProcessing(snapshots)

            // meta event is patched in
            expect(result).toHaveLength(3)
            const incrementalSnapshot = result.filter((s) => s.type === EventType.IncrementalSnapshot)
            expect(incrementalSnapshot).toHaveLength(1)

            expect(incrementalSnapshot[0].timestamp).toBe(1001)
            expect(
                Array.from(new Set((incrementalSnapshot[0].data as any).adds.map((a: any) => a.node.id)))
            ).toHaveLength(1000)
            expect((incrementalSnapshot[0].data as any).adds.length).toBe(1_000)
        })

        it('does throttle adds when high enough load is spread between nodes', () => {
            // Create a sequence of rapid mutations for the same node
            const snapshots: RecordingSnapshot[] = [
                createFullSnapshot(1000),
                ...createIncrementalSnapshot(1001, {
                    adds: createAdds(rotateIdsBetween(0, 1000), 500_000),
                }),
            ]

            expect((snapshots[1].data as any).adds.length).toBe(500_000)
            expect(Array.from(new Set((snapshots[1].data as any).adds.map((a: any) => a.node.id)))).toHaveLength(1000)

            const result = callProcessing(snapshots)

            // meta event is patched in
            expect(result).toHaveLength(3)
            const incrementalSnapshot = result.filter((s) => s.type === EventType.IncrementalSnapshot)
            expect(incrementalSnapshot).toHaveLength(1)

            expect(incrementalSnapshot[0].timestamp).toBe(1001)
            // still have at least one "add" for each node
            expect(
                Array.from(new Set((incrementalSnapshot[0].data as any).adds.map((a: any) => a.node.id)))
            ).toHaveLength(1000)
            expect((incrementalSnapshot[0].data as any).adds.length).toBe(1_000)
        })

        it('does throttle adds when load is concentrated on one node', () => {
            // Create a sequence of rapid mutations for the same node
            const snapshots: RecordingSnapshot[] = [
                createFullSnapshot(1000),
                ...createIncrementalSnapshot(1001, {
                    adds: createAdds(alwaysOneGenerator, 10_000),
                }),
            ]

            const result = callProcessing(snapshots)

            // meta event is patched in
            expect(result).toHaveLength(3)
            const incrementalSnapshot = result.filter((s) => s.type === EventType.IncrementalSnapshot)
            expect(incrementalSnapshot).toHaveLength(1)

            expect(incrementalSnapshot[0].timestamp).toBe(1001)
            expect((incrementalSnapshot[0].data as any).adds.length).toBe(1)
        })

        it('throttles adds when spread across different snapshots', () => {
            const snapshots: RecordingSnapshot[] = [
                createFullSnapshot(1000),
                ...createIncrementalSnapshot(
                    1001,
                    {
                        adds: createAdds(alwaysOneGenerator),
                    },
                    10_000
                ),
            ]
            expect(snapshots).toHaveLength(10_001)
            expect(snapshots.filter((s) => s.type === EventType.IncrementalSnapshot)).toHaveLength(10_000)

            const result = callProcessing(snapshots)

            // meta event is patched in
            expect(result).toHaveLength(1002)
            const incrementalSnapshot = result.filter((s) => s.type === EventType.IncrementalSnapshot)
            expect(incrementalSnapshot).toHaveLength(1000)
        })

        it('processes mutations for multiple nodes without throttling', () => {
            const snapshots: RecordingSnapshot[] = [
                createFullSnapshot(1000),
                // Node 1 mutations
                ...createIncrementalSnapshot(1001, {
                    adds: createAdds(alwaysOneGenerator),
                }),
                ...createIncrementalSnapshot(1002, {
                    texts: createTexts(alwaysOneGenerator),
                }),
                // Node 2 mutations
                ...createIncrementalSnapshot(1003, {
                    adds: createAdds(() => 2),
                }),
                ...createIncrementalSnapshot(1004, {
                    texts: createTexts(alwaysOneGenerator),
                }),
                // Rapid mutations for both nodes
                ...createIncrementalSnapshot(1005, {
                    texts: createTexts(alwaysOneGenerator),
                }),
                ...createIncrementalSnapshot(1005, {
                    texts: createTexts(alwaysTwoGenerator),
                }),
                ...createIncrementalSnapshot(1006, {
                    attributes: createAttributes(alwaysOneGenerator),
                }),
                ...createIncrementalSnapshot(1006, {
                    attributes: createAttributes(alwaysTwoGenerator),
                }),
            ]

            const result = callProcessing(snapshots)

            // Verify all mutations are processed
            expect(result.filter((s) => s.type === EventType.IncrementalSnapshot)).toHaveLength(8)

            // Verify order is preserved
            const incrementalSnapshots = result.filter((s) => s.type === EventType.IncrementalSnapshot)
            expect(incrementalSnapshots[0].timestamp).toBe(1001)
            expect(incrementalSnapshots[1].timestamp).toBe(1002)
            expect(incrementalSnapshots[2].timestamp).toBe(1003)
            expect(incrementalSnapshots[3].timestamp).toBe(1004)
            expect(incrementalSnapshots[4].timestamp).toBe(1005)
            expect(incrementalSnapshots[5].timestamp).toBe(1005)
            expect(incrementalSnapshots[6].timestamp).toBe(1006)
            expect(incrementalSnapshots[7].timestamp).toBe(1006)
        })

        it('resets state on full snapshot', () => {
            const snapshots: RecordingSnapshot[] = [
                createFullSnapshot(1000),
                ...createIncrementalSnapshot(1001, {
                    adds: createAdds(alwaysOneGenerator),
                }),
                ...createIncrementalSnapshot(1002, {
                    texts: createTexts(alwaysOneGenerator),
                }),
                createFullSnapshot(1003),
                ...createIncrementalSnapshot(1004, {
                    adds: createAdds(alwaysOneGenerator),
                }),
                ...createIncrementalSnapshot(1005, {
                    texts: createTexts(alwaysOneGenerator),
                }),
            ]

            const result = callProcessing(snapshots)

            // Verify all mutations are processed
            expect(result.filter((s) => s.type === EventType.IncrementalSnapshot)).toHaveLength(4)

            // Verify order is preserved
            const incrementalSnapshots = result.filter((s) => s.type === EventType.IncrementalSnapshot)
            expect(incrementalSnapshots[0].timestamp).toBe(1001)
            expect(incrementalSnapshots[1].timestamp).toBe(1002)
            expect(incrementalSnapshots[2].timestamp).toBe(1004)
            expect(incrementalSnapshots[3].timestamp).toBe(1005)
        })
    })
})

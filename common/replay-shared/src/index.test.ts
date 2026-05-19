import {
    parseEncodedSnapshots,
    parseJsonSnapshots,
    createWindowIdRegistry,
    SnapshotStore,
    createSegments,
    mapSnapshotsToWindowId,
    keyForSource,
    chunkMutationSnapshot,
    PLACEHOLDER_SVG_DATA_IMAGE_URL,
} from './index'

describe('@posthog/replay-shared', () => {
    describe('parseJsonSnapshots', () => {
        it('parses a JSON-encoded snapshot line', () => {
            const snapshot = { windowId: 'abc', type: 2, data: {}, timestamp: 1000 }
            const result = parseJsonSnapshots([JSON.stringify(snapshot)], 'session-1')
            expect(result).toHaveLength(1)
            expect(result[0].timestamp).toBe(1000)
        })

        it('returns empty array for empty input', () => {
            expect(parseJsonSnapshots([], 'session-1')).toEqual([])
        })
    })

    describe('parseEncodedSnapshots', () => {
        it('parses array of JSON strings', async () => {
            const snapshot = { windowId: 'abc', type: 2, data: {}, timestamp: 2000 }
            const result = await parseEncodedSnapshots([JSON.stringify(snapshot)], 'session-1')
            expect(result).toHaveLength(1)
            expect(result[0].timestamp).toBe(2000)
        })

        it('parses plain-text Uint8Array without decompressor', async () => {
            const snapshot = { windowId: 'abc', type: 2, data: {}, timestamp: 3000 }
            const encoded = new TextEncoder().encode(JSON.stringify(snapshot))
            const result = await parseEncodedSnapshots(encoded, 'session-1')
            expect(result).toHaveLength(1)
            expect(result[0].timestamp).toBe(3000)
        })

        it('uses injectable decompressor for binary data', async () => {
            const snapshot = { windowId: 'abc', type: 2, data: {}, timestamp: 4000 }
            const plaintext = new TextEncoder().encode(JSON.stringify(snapshot))
            const fakeCompressed = new Uint8Array([0, 0, 0, 5, 1, 2, 3, 4, 5])

            const decompressor = jest.fn().mockResolvedValue(plaintext)
            const result = await parseEncodedSnapshots(fakeCompressed, 'session-1', undefined, undefined, decompressor)
            expect(decompressor).toHaveBeenCalled()
            expect(result).toHaveLength(1)
            expect(result[0].timestamp).toBe(4000)
        })
    })

    describe('createWindowIdRegistry', () => {
        it('assigns stable integer ids to window UUIDs', () => {
            const register = createWindowIdRegistry()
            expect(register('window-a')).toBe(1)
            expect(register('window-b')).toBe(2)
            expect(register('window-a')).toBe(1)
        })
    })

    describe('SnapshotStore', () => {
        it('tracks sources and loaded state', () => {
            const store = new SnapshotStore()
            store.setSources([
                {
                    source: 'blob_v2',
                    blob_key: '0',
                    start_timestamp: '2023-01-01T00:00:00Z',
                    end_timestamp: '2023-01-01T00:01:00Z',
                },
            ])
            expect(store.sourceCount).toBe(1)
            expect(store.getUnloadedIndicesInRange(0, 0)).toEqual([0])

            store.markLoaded(0, [])
            expect(store.getUnloadedIndicesInRange(0, 0)).toEqual([])
        })
    })

    describe('createSegments', () => {
        it('creates a segment from snapshots', () => {
            const snapshots = [
                { type: 4, data: { href: 'http://example.com' }, timestamp: 1000, windowId: 1 },
                { type: 2, data: {}, timestamp: 1001, windowId: 1 },
            ] as any[]
            const byWindow = mapSnapshotsToWindowId(snapshots)
            const segments = createSegments(snapshots, null, null, null, byWindow)
            expect(segments.length).toBeGreaterThanOrEqual(1)
        })
    })

    describe('keyForSource', () => {
        it('creates a key from a blob source', () => {
            const key = keyForSource({ source: 'blob_v2', blob_key: 'abc' } as any)
            expect(key).toContain('abc')
        })
    })

    describe('chunkMutationSnapshot', () => {
        it('returns unchanged snapshot when mutations are small', () => {
            const snapshot = { type: 3, data: { source: 0, adds: [{ node: {} }] }, timestamp: 1000, windowId: 1 }
            const result = chunkMutationSnapshot(snapshot as any)
            expect(result).toHaveLength(1)
        })
    })

    describe('PLACEHOLDER_SVG_DATA_IMAGE_URL', () => {
        it('is a data URL string', () => {
            expect(PLACEHOLDER_SVG_DATA_IMAGE_URL).toContain('data:image/svg+xml;base64,')
        })
    })
})

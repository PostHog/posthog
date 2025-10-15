import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { getDecompressionWorkerManager } from './DecompressionWorkerManager'
import { hasAnyWireframes, parseEncodedSnapshots, processAllSnapshots } from './process-all-snapshots'
import { keyForSource } from './source-key'

// Mock the decompression worker manager
jest.mock('./DecompressionWorkerManager', () => ({
    getDecompressionWorkerManager: jest.fn(),
}))

const pathForKeyZero = join(__dirname, '../__mocks__/perf-snapshot-key0.jsonl')

const readFileContents = (path: string): string => {
    return readFileSync(path, 'utf-8')
}

const keyZero = readFileContents(pathForKeyZero)
// const keyOne = readFileContents(pathForKeyOne)

describe('process all snapshots', () => {
    describe('performance check', () => {
        it('can process all snapshots fast', async () => {
            const sessionId = '1234'
            const source = {
                source: 'blob_v2',
                blob_key: '0',
            } as SessionRecordingSnapshotSource
            const key = keyForSource(source)
            const rawSnapshots = keyZero.split('\n')
            const snapshots = await parseEncodedSnapshots(rawSnapshots, sessionId)
            expect(snapshots).toHaveLength(99)

            const start = performance.now()
            const results = processAllSnapshots(
                [
                    {
                        source: 'blob_v2',
                        blob_key: '0',
                    },
                ],
                {
                    [key]: {
                        snapshots: snapshots,
                    },
                },
                {},
                () => {
                    return {
                        width: '100',
                        height: '100',
                        href: 'https://example.com',
                    }
                },
                sessionId
            )
            const end = performance.now()
            const duration = end - start
            expect(results).toHaveLength(99)
            expect(duration).toBeLessThan(150) // Increased timeout to account for synthetic snapshot logic
        })

        it('deduplicates snapshot', async () => {
            const sessionId = '1234'
            const source = {
                source: 'blob_v2',
                blob_key: '0',
            } as SessionRecordingSnapshotSource
            const key = keyForSource(source)
            const results = processAllSnapshots(
                [
                    {
                        source: 'blob_v2',
                        blob_key: '0',
                    },
                ],
                {
                    [key]: {
                        snapshots: [
                            {
                                windowId: '1',
                                timestamp: 1234567890,
                                type: 0,
                                data: {
                                    width: '100',
                                    height: '100',
                                    href: 'https://example.com',
                                },
                            } as RecordingSnapshot,
                            {
                                windowId: '1',
                                timestamp: 1234567890,
                                type: 0,
                                data: {
                                    width: '100',
                                    height: '100',
                                    href: 'https://example.com',
                                },
                            } as RecordingSnapshot,
                        ],
                    },
                },
                {},
                () => {
                    return {
                        width: '100',
                        height: '100',
                        href: 'https://example.com',
                    }
                },
                sessionId
            )

            expect(results).toHaveLength(1)
        })
    })

    describe('hasAnyWireframes', () => {
        it('can detect a react native sdk 4.1.0 updates wireframe', () => {
            expect(
                hasAnyWireframes([
                    {
                        timestamp: 1751925097543,
                        data: {
                            source: 0,
                            updates: [
                                {
                                    wireframe: {
                                        base64: 'data:image/webp;base64,blahblah\n',
                                        height: 904,
                                        id: 172905027,
                                        style: {},
                                        type: 'screenshot',
                                        width: 406,
                                        x: 0,
                                        y: 0,
                                    },
                                },
                            ],
                        },
                        type: 3,
                    },
                ])
            ).toBeTruthy()
        })
    })

    describe('mobile recording with synthetic full snapshot', () => {
        // Mock the mobile replay module
        const mockMobileReplay = {
            transformEventToWeb: jest.fn(),
        }

        beforeEach(() => {
            jest.clearAllMocks()

            // Mock the posthogEE import to return our mock
            jest.doMock('@posthog/ee/exports', () => ({
                __esModule: true,
                default: () =>
                    Promise.resolve({
                        mobileReplay: mockMobileReplay,
                    }),
            }))
        })

        afterEach(() => {
            jest.dontMock('@posthog/ee/exports')
        })

        it('creates synthetic full snapshot when mobile recording starts with incremental snapshot', async () => {
            const sessionId = 'test-mobile-session'

            // Mock mobile incremental snapshot (type 3) with wireframes
            const mobileIncrementalSnapshot = {
                type: 3,
                timestamp: 1000,
                data: {
                    source: 0,
                    updates: [
                        {
                            wireframe: {
                                type: 'screenshot',
                                base64: 'data:image/webp;base64,test',
                                width: 400,
                                height: 800,
                                x: 0,
                                y: 0,
                            },
                        },
                    ],
                },
            }

            // Mock transformed web events
            const mockSyntheticFullSnapshot = {
                type: 2, // FullSnapshot
                timestamp: 999,
                data: {
                    node: {
                        type: 0,
                        childNodes: [],
                        id: 1,
                    },
                    initialOffset: { top: 0, left: 0 },
                },
            }

            const mockTransformedIncremental = {
                type: 3, // IncrementalSnapshot
                timestamp: 1000,
                data: {
                    source: 0,
                    adds: [],
                    removes: [],
                    texts: [],
                    attributes: [],
                },
            }

            // Setup mock to return different results for synthetic vs original events
            mockMobileReplay.transformEventToWeb
                .mockReturnValueOnce(mockSyntheticFullSnapshot) // First call for synthetic
                .mockReturnValueOnce(mockTransformedIncremental) // Second call for original

            const snapshotJson = JSON.stringify({
                window_id: '1',
                data: [mobileIncrementalSnapshot],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            // Should have 3 snapshots: meta event + synthetic full + original incremental
            expect(result).toHaveLength(3)

            // First snapshot should be the Meta event (inserted by patchMetaEventIntoMobileData before the full snapshot)
            expect(result[0].type).toBe(4) // Meta

            // Second snapshot should be the synthetic full snapshot
            expect(result[1].type).toBe(2) // FullSnapshot
            expect(result[1].timestamp).toBe(999)

            // Third snapshot should be the original incremental
            expect(result[2].type).toBe(3) // IncrementalSnapshot
            expect(result[2].timestamp).toBe(1000)

            // Verify transformEventToWeb was called twice
            expect(mockMobileReplay.transformEventToWeb).toHaveBeenCalledTimes(2)

            // First call should be for synthetic mobile full snapshot
            const firstCall = mockMobileReplay.transformEventToWeb.mock.calls[0][0]
            expect(firstCall.type).toBe(2) // FullSnapshot
            expect(firstCall.timestamp).toBe(999) // timestamp - 1
            expect(firstCall.data.wireframes).toEqual([])

            // Second call should be for original event
            const secondCall = mockMobileReplay.transformEventToWeb.mock.calls[1][0]
            expect(secondCall).toEqual(mobileIncrementalSnapshot)
        })

        it('does not create synthetic snapshot for non-mobile recordings', async () => {
            const sessionId = 'test-web-session'

            // Regular web incremental snapshot (no wireframes)
            const webIncrementalSnapshot = {
                type: 3,
                timestamp: 1000,
                data: {
                    source: 0,
                    adds: [],
                    removes: [],
                    texts: [],
                    attributes: [],
                },
            }

            const snapshotJson = JSON.stringify({
                window_id: '1',
                data: [webIncrementalSnapshot],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            // Should only have 1 snapshot (no synthetic one created)
            expect(result).toHaveLength(1)
            expect(result[0].type).toBe(3)
            expect(result[0].timestamp).toBe(1000)

            // transformEventToWeb should not be called for web recordings
            expect(mockMobileReplay.transformEventToWeb).not.toHaveBeenCalled()
        })

        it('does not create synthetic snapshot when mobile recording starts with full snapshot', async () => {
            const sessionId = 'test-mobile-session'

            // Mobile full snapshot (type 2) with wireframes
            const mobileFullSnapshot = {
                type: 2,
                timestamp: 1000,
                data: {
                    wireframes: [
                        {
                            type: 'screenshot',
                            base64: 'data:image/webp;base64,test',
                            width: 400,
                            height: 800,
                        },
                    ],
                    initialOffset: { top: 0, left: 0 },
                },
            }

            const mockTransformedFull = {
                type: 2,
                timestamp: 1000,
                data: {
                    node: {
                        type: 0,
                        childNodes: [],
                        id: 1,
                    },
                    initialOffset: { top: 0, left: 0 },
                },
            }

            mockMobileReplay.transformEventToWeb.mockReturnValue(mockTransformedFull)

            const snapshotJson = JSON.stringify({
                window_id: '1',
                data: [mobileFullSnapshot],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            // Should have 2 snapshots: Meta event (added by patchMetaEventIntoMobileData) + Full snapshot
            // No synthetic snapshot should be created since it already starts with a full snapshot
            expect(result).toHaveLength(2)

            // First event should be the Meta event (inserted by patchMetaEventIntoMobileData before the full snapshot)
            expect(result[0].type).toBe(4) // Meta
            expect(result[0].timestamp).toBe(1000)

            // Second event should be the original full snapshot
            expect(result[1].type).toBe(2) // FullSnapshot
            expect(result[1].timestamp).toBe(1000)
        })
    })

    describe('parseEncodedSnapshots with compressed data', () => {
        const mockWorkerManager = {
            decompress: jest.fn(),
            decompressBatch: jest.fn(),
            terminate: jest.fn(),
        }

        beforeEach(() => {
            jest.clearAllMocks()
            ;(getDecompressionWorkerManager as jest.Mock).mockReturnValue(mockWorkerManager)
        })

        const createLengthPrefixedData = (blocks: Uint8Array[]): Uint8Array => {
            let totalLength = 0
            for (const block of blocks) {
                totalLength += 4 + block.byteLength
            }

            const result = new Uint8Array(totalLength)
            let offset = 0

            for (const block of blocks) {
                const length = block.byteLength
                result[offset] = (length >>> 24) & 0xff
                result[offset + 1] = (length >>> 16) & 0xff
                result[offset + 2] = (length >>> 8) & 0xff
                result[offset + 3] = length & 0xff
                offset += 4

                result.set(block, offset)
                offset += length
            }

            return result
        }

        it.each([
            ['ArrayBuffer', (data: Uint8Array) => data.buffer as ArrayBuffer | Uint8Array],
            ['Uint8Array', (data: Uint8Array) => data],
        ])('handles %s input by decompressing and parsing', async (_name, convertInput) => {
            const sessionId = 'test-session'

            const snapshotJson = JSON.stringify({
                window_id: '1',
                data: [
                    {
                        type: 2,
                        timestamp: 1234567890,
                        data: { href: 'https://example.com' },
                    },
                ],
            })
            const decompressedBytes = new TextEncoder().encode(snapshotJson + '\n')
            const fakeCompressedBlock = new Uint8Array([1, 2, 3, 4, 5])
            const mockCompressedData = createLengthPrefixedData([fakeCompressedBlock])

            mockWorkerManager.decompress.mockResolvedValue(decompressedBytes)

            const result = await parseEncodedSnapshots(convertInput(mockCompressedData), sessionId)

            expect(mockWorkerManager.decompress).toHaveBeenCalledWith(fakeCompressedBlock)
            expect(result).toHaveLength(1)
            expect(result[0].windowId).toBe('1')
            expect(result[0].timestamp).toBe(1234567890)
        })

        it('handles multiple snapshots in decompressed data', async () => {
            const sessionId = 'test-session'

            const snapshot1 = JSON.stringify({
                window_id: '1',
                data: [{ type: 2, timestamp: 1000, data: {} }],
            })
            const snapshot2 = JSON.stringify({
                window_id: '1',
                data: [{ type: 3, timestamp: 2000, data: {} }],
            })
            const decompressedBytes1 = new TextEncoder().encode(snapshot1 + '\n')
            const decompressedBytes2 = new TextEncoder().encode(snapshot2 + '\n')

            const fakeCompressedBlock1 = new Uint8Array([1, 2, 3])
            const fakeCompressedBlock2 = new Uint8Array([4, 5, 6])
            const mockCompressedData = createLengthPrefixedData([fakeCompressedBlock1, fakeCompressedBlock2])

            mockWorkerManager.decompress
                .mockResolvedValueOnce(decompressedBytes1)
                .mockResolvedValueOnce(decompressedBytes2)

            const result = await parseEncodedSnapshots(mockCompressedData, sessionId)

            expect(result).toHaveLength(2)
            expect(result[0].timestamp).toBe(1000)
            expect(result[1].timestamp).toBe(2000)
        })

        it('returns empty array and logs error on decompression failure', async () => {
            const sessionId = 'test-session'
            const mockCompressedData = new Uint8Array([1, 2, 3])

            mockWorkerManager.decompress.mockRejectedValue(new Error('Decompression failed'))

            const result = await parseEncodedSnapshots(mockCompressedData, sessionId)

            expect(result).toHaveLength(0)
        })

        it('filters out empty lines in decompressed data', async () => {
            const sessionId = 'test-session'

            const snapshot = JSON.stringify({
                window_id: '1',
                data: [{ type: 2, timestamp: 1000, data: {} }],
            })
            const decompressedBytes = new TextEncoder().encode('\n\n' + snapshot + '\n\n\n')
            const fakeCompressedBlock = new Uint8Array([10, 11, 12])
            const mockCompressedData = createLengthPrefixedData([fakeCompressedBlock])

            mockWorkerManager.decompress.mockResolvedValue(decompressedBytes)

            const result = await parseEncodedSnapshots(mockCompressedData, sessionId)

            expect(result).toHaveLength(1)
        })
    })
})

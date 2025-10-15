import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { RecordingSnapshot, SessionRecordingSnapshotSource } from '~/types'

import { getDecompressionWorkerManager } from './DecompressionWorkerManager'
import { hasAnyWireframes, parseEncodedSnapshots, processAllSnapshots } from './process-all-snapshots'
import { keyForSource } from './source-key'

// Mock the EE exports early so modules under test see it when imported
jest.mock('@posthog/ee/exports', () => ({
    __esModule: true,
    default: jest.fn().mockResolvedValue({
        enabled: true,
        mobileReplay: {
            transformEventToWeb: jest.fn((event: any) => {
                // Transform mobile FullSnapshot (wireframes) into a rrweb-like full snapshot structure
                if (event?.type === 2 && event?.data?.wireframes !== undefined) {
                    return {
                        ...event,
                        data: {
                            node: {
                                childNodes: [
                                    {},
                                    {
                                        childNodes: [
                                            {},
                                            {
                                                childNodes: [
                                                    {
                                                        attributes: { width: 400, height: 800 },
                                                    },
                                                ],
                                            },
                                        ],
                                    },
                                ],
                            },
                            initialOffset: { top: 0, left: 0 },
                            href: 'https://example.com',
                        },
                    }
                }
                return event
            }),
        },
    }),
}))

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
            expect(duration).toBeLessThan(150)
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

    describe('mobile recording detection', () => {
        it('detects mobile recordings with wireframes in incremental updates', () => {
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

            expect(hasAnyWireframes([mobileIncrementalSnapshot])).toBe(true)
        })

        it('detects mobile recordings with wireframes in full snapshots', () => {
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

            expect(hasAnyWireframes([mobileFullSnapshot])).toBe(true)
        })

        it('does not detect web recordings as mobile', () => {
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

            expect(hasAnyWireframes([webIncrementalSnapshot])).toBe(false)
        })
    })

    describe('synthetic full snapshot creation', () => {
        it('creates synthetic full snapshot when mobile recording starts with incremental snapshot', async () => {
            const sessionId = 'test-mobile-session'

            const snapshotJson = JSON.stringify({
                window_id: '1',
                data: [
                    {
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
                    },
                ],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            expect(result.length).toBeGreaterThanOrEqual(2)
            expect(result[0].windowId).toBe('1')

            const hasFullSnapshot = result.some((r) => r.type === 2)
            const hasIncrementalSnapshot = result.some((r) => r.type === 3)
            expect(hasFullSnapshot).toBe(true)
            expect(hasIncrementalSnapshot).toBe(true)

            const fullSnapshot = result.find((r) => r.type === 2)
            const incrementalSnapshot = result.find((r) => r.type === 3)
            expect(fullSnapshot?.timestamp).toBe(999)
            expect(incrementalSnapshot?.timestamp).toBe(1000)
        })

        it('does not create synthetic snapshot when mobile recording starts with full snapshot', async () => {
            const sessionId = 'test-mobile-session'

            const snapshotJson = JSON.stringify({
                window_id: '1',
                data: [
                    {
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
                    },
                ],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            expect(result.length).toBeGreaterThanOrEqual(1)
            expect(result[0].windowId).toBe('1')

            const fullSnapshots = result.filter((r) => r.type === 2)
            expect(fullSnapshots).toHaveLength(1)
            expect(fullSnapshots[0].timestamp).toBe(1000)
        })

        it('does not create synthetic snapshot for web recordings', async () => {
            const sessionId = 'test-web-session'

            const snapshotJson = JSON.stringify({
                window_id: '1',
                data: [
                    {
                        type: 3,
                        timestamp: 1000,
                        data: {
                            source: 0,
                            adds: [],
                            removes: [],
                            texts: [],
                            attributes: [],
                        },
                    },
                ],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            expect(result).toHaveLength(1)
            expect(result[0].windowId).toBe('1')
            expect(result[0].type).toBe(3)

            const hasFullSnapshot = result.some((r) => r.type === 2)
            expect(hasFullSnapshot).toBe(false)
        })

        it('creates synthetic snapshot with correct windowId from original event', async () => {
            const sessionId = 'test-mobile-session'

            const snapshotJson = JSON.stringify({
                window_id: 'custom-window-123',
                data: [
                    {
                        type: 3,
                        timestamp: 2000,
                        data: {
                            source: 0,
                            updates: [
                                {
                                    wireframe: {
                                        type: 'screenshot',
                                        base64: 'data:image/webp;base64,test',
                                    },
                                },
                            ],
                        },
                    },
                ],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            result.forEach((event) => {
                expect(event.windowId).toBe('custom-window-123')
            })

            const fullSnapshot = result.find((r) => r.type === 2)
            expect(fullSnapshot?.timestamp).toBe(1999)
        })

        it('handles multiple mobile events correctly (only first gets synthetic)', async () => {
            const sessionId = 'test-mobile-session'

            const snapshotJson = JSON.stringify({
                window_id: '1',
                data: [
                    {
                        type: 3,
                        timestamp: 1000,
                        data: {
                            source: 0,
                            updates: [{ wireframe: { type: 'screenshot' } }],
                        },
                    },
                    {
                        type: 3,
                        timestamp: 2000,
                        data: {
                            source: 0,
                            updates: [{ wireframe: { type: 'screenshot' } }],
                        },
                    },
                ],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            expect(result.length).toBeGreaterThanOrEqual(2)

            const fullSnapshots = result.filter((r) => r.type === 2)
            expect(fullSnapshots).toHaveLength(1)
            expect(fullSnapshots[0].timestamp).toBe(999)

            const incrementalSnapshots = result.filter((r) => r.type === 3)
            expect(incrementalSnapshots).toHaveLength(2)
            expect(incrementalSnapshots[0].timestamp).toBe(1000)
            expect(incrementalSnapshots[1].timestamp).toBe(2000)
        })

        it('preserves original event data when creating synthetic snapshot', async () => {
            const sessionId = 'test-mobile-session'

            const originalEventData = {
                source: 0,
                updates: [
                    {
                        wireframe: {
                            type: 'screenshot',
                            base64: 'data:image/webp;base64,original-data',
                            width: 400,
                            height: 800,
                        },
                    },
                ],
            }

            const snapshotJson = JSON.stringify({
                window_id: '1',
                data: [
                    {
                        type: 3,
                        timestamp: 1000,
                        data: originalEventData,
                    },
                ],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            const originalEvent = result.find((r) => r.type === 3 && r.timestamp === 1000)
            expect(originalEvent).toBeTruthy()
            expect(originalEvent?.data).toEqual(originalEventData)
        })

        it('handles edge cases gracefully', async () => {
            const sessionId = 'test-edge-cases'

            const emptyWireframesJson = JSON.stringify({
                window_id: '1',
                data: [
                    {
                        type: 3,
                        timestamp: 1000,
                        data: {
                            source: 0,
                            updates: [
                                {
                                    wireframe: {
                                        type: 'screenshot',
                                        base64: '',
                                        width: 0,
                                        height: 0,
                                    },
                                },
                            ],
                        },
                    },
                ],
            })

            const result = await parseEncodedSnapshots([emptyWireframesJson], sessionId)

            const hasFullSnapshot = result.some((r) => r.type === 2)
            expect(hasFullSnapshot).toBe(true)
        })

        it('handles missing windowId gracefully', async () => {
            const sessionId = 'test-missing-windowid'

            const snapshotJson = JSON.stringify({
                window_id: '1',
                data: [
                    {
                        type: 3,
                        timestamp: 1000,
                        data: {
                            source: 0,
                            updates: [{ wireframe: { type: 'screenshot' } }],
                        },
                    },
                ],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            expect(result.length).toBeGreaterThan(0)
            result.forEach((event) => {
                expect(event.windowId).toBe('1')
            })
        })
    })
})

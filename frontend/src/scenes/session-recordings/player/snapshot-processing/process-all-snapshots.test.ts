import { RecordingSnapshot } from '~/types'

import { getDecompressionWorkerManager } from './DecompressionWorkerManager'
import { hasAnyWireframes, parseEncodedSnapshots } from './process-all-snapshots'

jest.mock('scenes/session-recordings/mobile-replay', () => ({
    transformEventToWeb: jest.fn((event: any) => {
        if (event?.type === 2 && event?.data?.wireframes !== undefined) {
            const firstWireframe = event.data.wireframes[0]
            const width = firstWireframe?.width || 400
            const height = firstWireframe?.height || 800
            return {
                ...event,
                data: {
                    node: {
                        type: 0,
                        childNodes: [
                            {
                                type: 1,
                                name: 'html',
                                id: 2,
                            },
                            {
                                type: 2,
                                tagName: 'html',
                                id: 3,
                                childNodes: [
                                    {
                                        type: 2,
                                        tagName: 'head',
                                        id: 4,
                                        childNodes: [],
                                    },
                                    {
                                        type: 2,
                                        tagName: 'body',
                                        id: 5,
                                        attributes: { 'data-rrweb-id': 5 },
                                        childNodes: [
                                            {
                                                type: 2,
                                                tagName: 'img',
                                                id: 100,
                                                attributes: {
                                                    'data-rrweb-id': 100,
                                                    width,
                                                    height,
                                                    src: 'data:image/png;base64,test',
                                                },
                                                childNodes: [],
                                            },
                                        ],
                                    },
                                ],
                            },
                        ],
                        id: 1,
                    },
                    initialOffset: { top: 0, left: 0 },
                    href: 'https://example.com',
                },
            }
        }

        if (event?.type === 3 && event?.data?.updates && Array.isArray(event.data.updates)) {
            const updates = event.data.updates
            if (updates.some((u: any) => u.wireframe)) {
                const firstUpdate = updates.find((u: any) => u.wireframe)
                const wireframe = firstUpdate?.wireframe
                const width = wireframe?.width || 400
                const height = wireframe?.height || 800

                return {
                    ...event,
                    data: {
                        source: 0,
                        adds: [
                            {
                                parentId: 5,
                                nextId: null,
                                node: {
                                    type: 2,
                                    tagName: 'img',
                                    id: 100,
                                    attributes: {
                                        'data-rrweb-id': 100,
                                        width,
                                        height,
                                        src: 'data:image/png;base64,test',
                                    },
                                    childNodes: [],
                                },
                            },
                        ],
                        removes: [],
                        texts: [],
                        attributes: [],
                    },
                }
            }
        }

        return event
    }),
}))

jest.mock('./DecompressionWorkerManager', () => ({
    getDecompressionWorkerManager: jest.fn(),
}))

describe('process all snapshots', () => {
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

            expect(mockWorkerManager.decompress).toHaveBeenCalledWith(fakeCompressedBlock, { isParallel: false })
            expect(result).toHaveLength(1)
            expect(result[0].windowId).toBe(1)
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

        it('handles raw Snappy compressed data (LTS format)', async () => {
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
            const fakeRawSnappyData = new Uint8Array([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b])

            mockWorkerManager.decompress.mockResolvedValue(decompressedBytes)

            const result = await parseEncodedSnapshots(fakeRawSnappyData, sessionId)

            expect(mockWorkerManager.decompress).toHaveBeenCalledWith(fakeRawSnappyData, { isParallel: false })
            expect(result).toHaveLength(1)
            expect(result[0].windowId).toBe(1)
            expect(result[0].timestamp).toBe(1234567890)
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

    describe('parseEncodedSnapshots', () => {
        it('transforms mobile event data during parsing', async () => {
            const sessionId = 'test-mobile-session'

            const mobileEventData = {
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
                        data: mobileEventData,
                    },
                ],
            })

            const result = await parseEncodedSnapshots([snapshotJson], sessionId)

            const transformedEvent = result.find((r: RecordingSnapshot) => r.type === 3 && r.timestamp === 1000)
            expect(transformedEvent).toBeTruthy()
            expect(transformedEvent?.data).toMatchObject({
                source: 0,
                adds: expect.arrayContaining([
                    expect.objectContaining({
                        node: expect.objectContaining({
                            tagName: 'img',
                            attributes: expect.objectContaining({
                                'data-rrweb-id': expect.any(Number),
                                width: 400,
                                height: 800,
                            }),
                        }),
                    }),
                ]),
            })
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
            result.forEach((event: RecordingSnapshot) => {
                expect(event.windowId).toBe(1)
            })
        })
    })
})

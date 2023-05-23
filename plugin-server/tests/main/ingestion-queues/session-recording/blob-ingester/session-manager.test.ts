import { Upload } from '@aws-sdk/lib-storage'
import { createReadStream, writeFileSync } from 'fs'
import { appendFile, unlink } from 'fs/promises'
import { DateTime, Settings } from 'luxon'

import { defaultConfig } from '../../../../../src/config/config'
import { PendingChunks } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/pending-chunks'
import { SessionManager } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/session-manager'
import { IncomingRecordingMessage } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/types'
import { compressToString } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/utils'
import { createChunkedIncomingRecordingMessage, createIncomingRecordingMessage } from '../fixtures'

jest.mock('fs', () => {
    return {
        ...jest.requireActual('fs'),
        writeFileSync: jest.fn(),
        createReadStream: jest.fn().mockImplementation(() => {
            return {
                pipe: jest.fn(),
            }
        }),
    }
})

jest.mock('@aws-sdk/lib-storage', () => {
    const mockUpload = jest.fn().mockImplementation(() => {
        return {
            done: jest.fn().mockResolvedValue(undefined),
        }
    })

    return {
        __esModule: true,
        Upload: mockUpload,
    }
})

jest.mock('fs/promises', () => {
    return {
        ...jest.requireActual('fs/promises'),
        unlink: jest.fn().mockResolvedValue(undefined),
        appendFile: jest.fn().mockResolvedValue(undefined),
    }
})

describe('session-manager', () => {
    let sessionManager: SessionManager
    const mockFinish = jest.fn()
    const mockS3Client: any = {
        send: jest.fn(),
    }

    const mockRealtimeManager: any = {
        clearAllMessages: jest.fn(),
        onSubscriptionEvent: jest.fn(),
        clearMessages: jest.fn(),
        addMessage: jest.fn(),
        addMessagesFromBuffer: jest.fn(),
    }

    beforeEach(() => {
        // it's always May 25
        Settings.now = () => new Date(2018, 4, 25).valueOf()

        sessionManager = new SessionManager(
            defaultConfig,
            mockS3Client,
            mockRealtimeManager,
            1,
            'session_id_1',
            1,
            'topic',
            mockFinish
        )
        mockFinish.mockClear()
    })

    afterEach(() => {
        // it's no longer always May 25
        Settings.now = () => new Date().valueOf()
    })

    it('adds a message', async () => {
        const payload = JSON.stringify([{ simple: 'data' }])
        const event = createIncomingRecordingMessage({
            data: compressToString(payload),
        })

        const messageTimestamp = DateTime.now().toMillis() - 10000
        event.metadata.timestamp = messageTimestamp
        await sessionManager.add(event)

        expect(sessionManager.buffer).toEqual({
            count: 1,
            oldestKafkaTimestamp: messageTimestamp,
            file: expect.any(String),
            id: expect.any(String),
            size: 61, // The size of the event payload - this may change when test data changes
            offsets: [1],
            eventsRange: {
                firstTimestamp: 1679568043305,
                lastTimestamp: 1679568043305,
            },
        })

        // the buffer file was created
        expect(writeFileSync).toHaveBeenCalledWith(sessionManager.buffer.file, '', 'utf-8')
    })

    it('does not flush if it has received a message recently', async () => {
        const payload = JSON.stringify([{ simple: 'data' }])
        const event = createIncomingRecordingMessage({
            data: compressToString(payload),
        })

        const flushThreshold = 2500 // any value here...
        const now = DateTime.now()
        event.metadata.timestamp = now
            .minus({
                milliseconds: flushThreshold - 10, // less than the threshold
            })
            .toMillis()
        await sessionManager.add(event)

        await sessionManager.flushIfSessionBufferIsOld(now.toMillis(), flushThreshold)

        // as a proxy for flush having been called or not
        expect(createReadStream).not.toHaveBeenCalled()
    })

    it('does flush if it has not received a message recently', async () => {
        const firstTimestamp = 1679568043305
        const lastTimestamp = 1679568043305 + 4000

        const payload = JSON.stringify([{ simple: 'data' }])
        const eventOne = createIncomingRecordingMessage({
            data: compressToString(payload),
            events_summary: [
                {
                    timestamp: firstTimestamp,
                    type: 4,
                    data: { href: 'http://localhost:3001/', width: 2560, height: 1304 },
                },
            ],
        })
        const eventTwo = createIncomingRecordingMessage({
            data: compressToString(payload),
            events_summary: [
                {
                    timestamp: lastTimestamp,
                    type: 4,
                    data: { href: 'http://localhost:3001/', width: 2560, height: 1304 },
                },
            ],
        })

        const flushThreshold = 2500 // any value here...
        eventOne.metadata.timestamp = DateTime.now().minus({ milliseconds: flushThreshold }).toMillis()
        await sessionManager.add(eventOne)
        eventTwo.metadata.timestamp = DateTime.now().minus({ milliseconds: flushThreshold }).toMillis()
        await sessionManager.add(eventTwo)

        await sessionManager.flushIfSessionBufferIsOld(DateTime.now().toMillis(), flushThreshold)

        // as a proxy for flush having been called or not
        expect(createReadStream).toHaveBeenCalled()
        const mockUploadCalls = (Upload as unknown as jest.Mock).mock.calls
        expect(mockUploadCalls.length).toBe(1)
        expect(mockUploadCalls[0].length).toBe(1)
        expect(mockUploadCalls[0][0]).toEqual(
            expect.objectContaining({
                params: expect.objectContaining({
                    Key: `session_recordings/team_id/1/session_id/session_id_1/data/${firstTimestamp}-${lastTimestamp}`,
                }),
            })
        )
    })

    it('does not flush a short session even when lagging if within threshold', async () => {
        const payload = JSON.stringify([{ simple: 'data' }])
        const event = createIncomingRecordingMessage({
            data: compressToString(payload),
        })

        // a timestamp that means the message is older than threshold and all-things-being-equal should flush
        // uses timestamps offset from now to show this logic still works even if the consumer is running behind
        const aDayInMilliseconds = 24 * 60 * 60 * 1000
        const now = DateTime.now()
        event.metadata.timestamp = now.minus({ milliseconds: aDayInMilliseconds - 3500 }).toMillis()

        await sessionManager.add(event)

        await sessionManager.flushIfSessionBufferIsOld(now.minus({ milliseconds: aDayInMilliseconds }).toMillis(), 2500)

        // as a proxy for flush having been called or not
        expect(createReadStream).not.toHaveBeenCalled()
    })

    it('flushes messages', async () => {
        const event = createIncomingRecordingMessage()
        await sessionManager.add(event)
        expect(sessionManager.buffer.count).toEqual(1)
        const file = sessionManager.buffer.file
        expect(unlink).not.toHaveBeenCalled()

        const afterResumeFlushPromise = sessionManager.flush('buffer_size')

        expect(sessionManager.buffer.count).toEqual(0)
        expect(sessionManager.flushBuffer?.count).toEqual(1)

        await afterResumeFlushPromise

        expect(sessionManager.flushBuffer).toEqual(undefined)
        expect(mockFinish).toBeCalledTimes(1)
        expect(unlink).toHaveBeenCalledWith(file)
    })

    it('flushes messages and whilst collecting new ones', async () => {
        const event = createIncomingRecordingMessage()
        const event2 = createIncomingRecordingMessage({
            data: compressToString(JSON.stringify([{ second: 'event' }])),
        })
        await sessionManager.add(event)
        expect(sessionManager.buffer.count).toEqual(1)

        const firstBufferFile = sessionManager.buffer.file

        const flushPromise = sessionManager.flush('buffer_size')
        await sessionManager.add(event2)

        // that the second event is in a new buffer file
        // that the original buffer file is deleted
        expect(sessionManager.buffer.file).toBeDefined()
        expect(sessionManager.buffer.file).not.toEqual(firstBufferFile)

        await flushPromise

        expect(sessionManager.flushBuffer).toEqual(undefined)
        expect(sessionManager.buffer.count).toEqual(1)
        expect(appendFile).toHaveBeenCalledWith(
            sessionManager.buffer.file,
            '{"window_id":"window_id_1","data":"[{\\"second\\":\\"event\\"}]"}\n',
            'utf-8'
        )
    })

    it('chunks incoming messages', async () => {
        const events = createChunkedIncomingRecordingMessage(3, {
            data: compressToString(JSON.stringify([{ simple: 'data' }])),
        })

        expect(events.length).toEqual(3)

        expect(events[0].data.length).toBeGreaterThan(1)
        expect(events[1].data.length).toBeGreaterThan(1)
        expect(events[2].data.length).toBeGreaterThan(1)

        await sessionManager.add(events[0])
        expect(sessionManager.buffer.count).toEqual(0)
        expect(sessionManager.chunks.size).toEqual(1)

        await sessionManager.add(events[2])
        expect(sessionManager.buffer.count).toEqual(0)
        expect(sessionManager.chunks.size).toEqual(1)

        await sessionManager.add(events[1])
        expect(sessionManager.buffer.count).toEqual(1)
        expect(sessionManager.chunks.size).toEqual(0)

        // the file was created
        expect(writeFileSync).toHaveBeenCalledWith(sessionManager.buffer.file, '', 'utf-8')
        // the data was written
        expect(appendFile).toHaveBeenCalledWith(
            sessionManager.buffer.file,
            '{"window_id":"window_id_1","data":"[{\\"simple\\":\\"data\\"}]"}\n',
            'utf-8'
        )
    })

    it.each([
        [
            'incomplete and below threshold, we keep it in the chunks buffer',
            2000,
            { '1': [{ chunk_count: 2, chunk_index: 1, metadata: { timestamp: 1000 } } as IncomingRecordingMessage] },
            { '1': [{ chunk_count: 2, chunk_index: 1, metadata: { timestamp: 1000 } } as IncomingRecordingMessage] },
            [],
        ],
        [
            'incomplete and over the threshold, drop the chunks copying the offsets into the buffer',
            2500,
            {
                '1': [
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 1000, offset: 245 },
                    } as IncomingRecordingMessage,
                ],
            },
            {},
            [245],
        ],
        [
            'over-complete and over the threshold, should not be possible - do nothing',
            2500,
            {
                '1': [
                    {
                        chunk_count: 2,
                        chunk_index: 0,
                        data: 'H4sIAAAAAAAAE4tmqGZQYihmyGTIZShgy',
                        metadata: { timestamp: 997, offset: 123 },
                    } as IncomingRecordingMessage,
                    //receives chunk two three times 😱
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        data: 'GFIBfKsgDiFIZGhBIiVGGoZYhkAOTL8NSYAAAA=',
                        metadata: { timestamp: 998, offset: 124 },
                    } as IncomingRecordingMessage,
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 999, offset: 125 },
                    } as IncomingRecordingMessage,
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 1000, offset: 126 },
                    } as IncomingRecordingMessage,
                ],
            },
            {
                '1': [
                    {
                        chunk_count: 2,
                        chunk_index: 0,
                        data: 'H4sIAAAAAAAAE4tmqGZQYihmyGTIZShgy',
                        metadata: { timestamp: 997, offset: 123 },
                    } as IncomingRecordingMessage,
                    //receives chunk two three times 😱
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        data: 'GFIBfKsgDiFIZGhBIiVGGoZYhkAOTL8NSYAAAA=',
                        metadata: { timestamp: 998, offset: 124 },
                    } as IncomingRecordingMessage,
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 999, offset: 125 },
                    } as IncomingRecordingMessage,
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 1000, offset: 126 },
                    } as IncomingRecordingMessage,
                ],
            },
            [],
        ],
        [
            'over-complete and under the threshold,do nothing',
            1000,
            {
                '1': [
                    //receives chunk two three times 😱
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        data: 'GFIBfKsgDiFIZGhBIiVGGoZYhkAOTL8NSYAAAA=',
                        metadata: { timestamp: 998, offset: 245 },
                    } as IncomingRecordingMessage,
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 999, offset: 246 },
                    } as IncomingRecordingMessage,
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 1000, offset: 247 },
                    } as IncomingRecordingMessage,
                ],
            },
            {
                '1': [
                    //receives chunk two three times 😱
                    // drops one of the duplicates in the processing
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        data: 'GFIBfKsgDiFIZGhBIiVGGoZYhkAOTL8NSYAAAA=',
                        metadata: { timestamp: 998, offset: 245 },
                    } as IncomingRecordingMessage,
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 999, offset: 246 },
                    } as IncomingRecordingMessage,
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 1000, offset: 247 },
                    } as IncomingRecordingMessage,
                ],
            },
            [],
        ],
        [
            'over-complete and over the threshold, but not all chunks are present, drop the chunks',
            4000,
            {
                1: [
                    //receives chunk two three times 😱
                    // worse, the chunk is decompressible even though it is not complete
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        data: 'GFIBfKsgDiFIZGhBIiVGGoZYhkAOTL8NSYAAAA=',
                        metadata: { timestamp: 998, offset: 245 },
                    } as IncomingRecordingMessage,
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 999, offset: 246 },
                    } as IncomingRecordingMessage,
                    {
                        chunk_count: 2,
                        chunk_index: 1,
                        metadata: { timestamp: 1000, offset: 247 },
                    } as IncomingRecordingMessage,
                ],
            },
            {},
            [245, 246, 247],
        ],
    ])(
        'correctly handles pending chunks - %s',
        (
            _description: string,
            referenceNow: number,
            chunks: Record<string, IncomingRecordingMessage[]>,
            expectedChunks: Record<string, IncomingRecordingMessage[]>,
            expectedBufferOffsets: number[]
        ) => {
            const pendingChunks = new Map<string, PendingChunks>()
            Object.entries(chunks).forEach(([key, value]) => {
                const pc = new PendingChunks(value[0])
                ;(value as IncomingRecordingMessage[]).slice(1).forEach((chunk) => pc.add(chunk))
                pendingChunks.set(key, pc)
            })

            const actualChunks = sessionManager.handleIdleChunks(pendingChunks, referenceNow, 1000, {})
            expect(actualChunks.size).toEqual(Object.keys(expectedChunks).length)
            Object.entries(expectedChunks).forEach(([key, value]) => {
                expect(actualChunks.get(key)?.chunks).toEqual(value)
            })
            expect(sessionManager.buffer.offsets).toEqual(expectedBufferOffsets)
        }
    )
})

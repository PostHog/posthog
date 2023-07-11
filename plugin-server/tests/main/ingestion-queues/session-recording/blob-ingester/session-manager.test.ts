import { Upload } from '@aws-sdk/lib-storage'
import { createReadStream, createWriteStream } from 'fs'
import { unlink } from 'fs/promises'
import { DateTime, Settings } from 'luxon'

import { defaultConfig } from '../../../../../src/config/config'
import { SessionManager } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/session-manager'
import { now } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/utils'
import { createIncomingRecordingMessage } from '../fixtures'

jest.mock('fs', () => {
    return {
        ...jest.requireActual('fs'),
        writeFileSync: jest.fn(),
        createReadStream: jest.fn().mockImplementation(() => {
            return {
                pipe: () => ({ close: jest.fn() }),
            }
        }),
        createWriteStream: jest.fn().mockImplementation(() => {
            return {
                write: jest.fn(),
                pipe: () => ({ close: jest.fn() }),
                end: jest.fn(),
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
        onSubscriptionEvent: jest.fn(() => jest.fn()),
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

    afterEach(async () => {
        await sessionManager.destroy()
        // it's no longer always May 25
        Settings.now = () => new Date().valueOf()
    })

    it('adds a message', () => {
        const timestamp = now() - 10000
        const event = createIncomingRecordingMessage({
            metadata: {
                timestamp: timestamp,
            } as any,
        })

        sessionManager.add(event)

        expect(sessionManager.buffer).toEqual({
            count: 1,
            oldestKafkaTimestamp: timestamp,
            newestKafkaTimestamp: timestamp,
            file: expect.any(String),
            fileStream: expect.any(Object),
            id: expect.any(String),
            offsets: {
                highest: 1,
                lowest: 1,
            },
            createdAt: now(),
            eventsRange: {
                firstTimestamp: 1679568314158,
                lastTimestamp: 1679568314158,
            },
        })

        // the buffer file was created
        expect(createWriteStream).toHaveBeenCalledWith(sessionManager.buffer.file, 'utf-8')
    })

    it('does not flush if it has received a message recently', async () => {
        const flushThreshold = 2500 // any value here...
        const now = DateTime.now()

        const event = createIncomingRecordingMessage({
            metadata: {
                timestamp: now
                    .minus({
                        milliseconds: flushThreshold - 10, // less than the threshold
                    })
                    .toMillis(),
            } as any,
        })

        sessionManager.add(event)
        await sessionManager.flushIfSessionBufferIsOld(now.toMillis(), flushThreshold)

        // as a proxy for flush having been called or not
        expect(createReadStream).not.toHaveBeenCalled()
    })

    it('does flush if it has not received a message recently', async () => {
        const flushThreshold = 2500 // any value here...
        const firstTimestamp = 1679568043305
        const lastTimestamp = 1679568043305 + 4000

        const eventOne = createIncomingRecordingMessage({
            events: [
                {
                    timestamp: firstTimestamp,
                    type: 4,
                    data: { href: 'http://localhost:3001/', width: 2560, height: 1304 },
                },
            ],
            metadata: {
                // the highest offset doesn't have to be received first!
                offset: 12345,
                timestamp: DateTime.now().minus({ milliseconds: flushThreshold }).toMillis(),
            } as any,
        })
        const eventTwo = createIncomingRecordingMessage({
            events: [
                {
                    timestamp: lastTimestamp,
                    type: 4,
                    data: { href: 'http://localhost:3001/', width: 2560, height: 1304 },
                },
            ],
            metadata: {
                offset: 12344,
                timestamp: DateTime.now().minus({ milliseconds: flushThreshold }).toMillis(),
            } as any,
        })

        sessionManager.add(eventOne)
        sessionManager.add(eventTwo)

        await sessionManager.flushIfSessionBufferIsOld(now(), flushThreshold)

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
        // a timestamp that means the message is older than threshold and all-things-being-equal should flush
        // uses timestamps offset from now to show this logic still works even if the consumer is running behind
        const aDayInMilliseconds = 24 * 60 * 60 * 1000
        const now = DateTime.now()

        const event = createIncomingRecordingMessage({
            metadata: {
                timestamp: now.minus({ milliseconds: aDayInMilliseconds - 3500 }).toMillis(),
            } as any,
        })

        sessionManager.add(event)

        await sessionManager.flushIfSessionBufferIsOld(now.minus({ milliseconds: aDayInMilliseconds }).toMillis(), 2500)

        // as a proxy for flush having been called or not
        expect(createReadStream).not.toHaveBeenCalled()
    })

    it('does flush if lagging but nonetheless too old', async () => {
        const aDayInMilliseconds = 24 * 60 * 60 * 1000
        const now = DateTime.now()

        const event = createIncomingRecordingMessage({
            metadata: {
                timestamp: now.minus({ milliseconds: aDayInMilliseconds - 3500 }).toMillis(),
            } as any,
        })

        sessionManager.add(event)
        await sessionManager.flushIfSessionBufferIsOld(now.minus({ milliseconds: aDayInMilliseconds }).toMillis(), 2500)
        expect(createReadStream).not.toHaveBeenCalled()

        // Manually modify the date to simulate this being idle for too long
        sessionManager.buffer.createdAt = now.minus({ milliseconds: 6000 }).toMillis()
        await sessionManager.flushIfSessionBufferIsOld(now.minus({ milliseconds: aDayInMilliseconds }).toMillis(), 2500)
        expect(createReadStream).toHaveBeenCalled()
    })

    it('flushes messages', async () => {
        const event = createIncomingRecordingMessage()
        sessionManager.add(event)
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
            events: [{ timestamp: 1234, type: 4, data: { href: 'http://localhost:3001/' } }],
        })
        sessionManager.add(event)
        expect(sessionManager.buffer.count).toEqual(1)

        const firstBufferFile = sessionManager.buffer.file
        const flushPromise = sessionManager.flush('buffer_size')
        sessionManager.add(event2)

        // that the second event is in a new buffer file
        // that the original buffer file is deleted
        expect(sessionManager.buffer.file).toBeDefined()
        expect(sessionManager.buffer.file).not.toEqual(firstBufferFile)

        const flushWriteSteamMock = sessionManager.flushBuffer?.fileStream?.write as jest.Mock

        await flushPromise

        expect(sessionManager.flushBuffer).toEqual(undefined)
        expect(sessionManager.buffer.count).toEqual(1)
        const bufferWriteSteamMock = sessionManager.buffer.fileStream.write as jest.Mock

        expect(flushWriteSteamMock.mock.calls.length).toBe(1)
        expect(bufferWriteSteamMock.mock.calls.length).toBe(1)
        const lastCall = bufferWriteSteamMock.mock.calls[0]
        expect(lastCall).toEqual([
            '{"window_id":"window_id_1","data":[{"timestamp":1234,"type":4,"data":{"href":"http://localhost:3001/"}}]}\n',
        ])
    })

    it('tracks the offsets', () => {
        const addEvent = (offset: number) =>
            sessionManager.add(
                createIncomingRecordingMessage({
                    metadata: {
                        offset,
                    } as any,
                })
            )

        addEvent(4)

        expect(sessionManager.buffer.offsets).toEqual({
            highest: 4,
            lowest: 4,
        })

        addEvent(10)

        expect(sessionManager.buffer.offsets).toEqual({
            highest: 10,
            lowest: 4,
        })

        addEvent(2)

        expect(sessionManager.buffer.offsets).toEqual({
            highest: 10,
            lowest: 2,
        })
    })
})

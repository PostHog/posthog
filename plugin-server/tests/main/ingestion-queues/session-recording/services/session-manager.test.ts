import { Upload } from '@aws-sdk/lib-storage'
import { createReadStream, createWriteStream } from 'fs'
import { DateTime, Settings } from 'luxon'

import { defaultConfig } from '../../../../../src/config/config'
import { SessionManager } from '../../../../../src/main/ingestion-queues/session-recording/services/session-manager'
import { now } from '../../../../../src/main/ingestion-queues/session-recording/utils'
import { createIncomingRecordingMessage } from '../fixtures'

class MockStream {
    write = jest.fn(() => true)
    close = jest.fn((cb) => cb?.())
    end = jest.fn((cb) => cb?.())
    on = jest.fn()
    once = jest.fn((val, cb) => cb?.())
}

jest.mock('fs', () => {
    return {
        ...jest.requireActual('fs'),
        writeFileSync: jest.fn(),
        createReadStream: jest.fn(() => new MockStream()),
        createWriteStream: jest.fn(() => new MockStream()),
    }
})

jest.mock('stream/promises', () => {
    return {
        ...jest.requireActual('stream/promises'),
        pipeline: jest.fn(
            () =>
                new Promise<void>((_res) => {
                    // do nothing
                })
        ),
    }
})

jest.mock('stream', () => {
    return {
        ...jest.requireActual('stream'),
        PassThrough: jest.fn(() => new MockStream()),
    }
})

jest.mock('@aws-sdk/lib-storage', () => {
    const mockUpload = jest.fn().mockImplementation(() => {
        return {
            abort: jest.fn().mockResolvedValue(undefined),
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
    jest.setTimeout(1000)
    let sessionManager: SessionManager
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

    const mockOffsetHighWaterMarker: any = {
        add: jest.fn(() => Promise.resolve()),
    }

    const createSessionManager = () => {
        return new SessionManager(
            defaultConfig,
            mockS3Client,
            mockRealtimeManager,
            mockOffsetHighWaterMarker,
            1,
            'session_id_1',
            1,
            'topic'
        )
    }

    const flushThreshold = defaultConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS * 1000

    beforeEach(() => {
        // it's always May 25
        Settings.now = () => new Date(2018, 4, 25).valueOf()

        sessionManager = createSessionManager()
    })

    afterEach(async () => {
        await sessionManager.destroy()
        // it's no longer always May 25
        Settings.now = () => new Date().valueOf()
    })

    it('adds a message', async () => {
        const timestamp = now() - 10000
        const event = createIncomingRecordingMessage({
            metadata: {
                timestamp: timestamp,
            } as any,
        })

        await sessionManager.add(event)

        expect(sessionManager.buffer).toEqual({
            count: 1,
            sizeEstimate: 4139,
            oldestKafkaTimestamp: timestamp,
            newestKafkaTimestamp: timestamp,
            file: expect.any(Function),
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
        expect(createWriteStream).toHaveBeenCalledWith(sessionManager.buffer.file('jsonl'))
        expect(createWriteStream).toHaveBeenCalledWith(sessionManager.buffer.file('gz'))
    })

    it('does not flush if it has received a message recently', async () => {
        const now = DateTime.now()

        const event = createIncomingRecordingMessage({
            metadata: {
                timestamp: now
                    .minus({
                        milliseconds: flushThreshold * 0.5, // less than the threshold
                    })
                    .toMillis(),
            } as any,
        })

        await sessionManager.add(event)
        await sessionManager.flushIfSessionBufferIsOld(now.toMillis())

        // as a proxy for flush having been called or not
        expect(createReadStream).not.toHaveBeenCalled()
    })

    it('does flush if it has not received a message recently', async () => {
        const firstTimestamp = 1679568043305
        const lastTimestamp = 1679568043305 + 4000

        const eventOne = createIncomingRecordingMessage({
            eventsRange: {
                start: firstTimestamp,
                end: firstTimestamp,
            },
            eventsByWindowId: {
                window_id_1: [
                    {
                        timestamp: firstTimestamp,
                        type: 4,
                        data: { href: 'http://localhost:3001/', width: 2560, height: 1304 },
                    },
                ],
            },
            metadata: {
                // the highest offset doesn't have to be received first!
                offset: 12345,
                timestamp: DateTime.now().minus({ milliseconds: flushThreshold }).toMillis(),
            } as any,
        })
        const eventTwo = createIncomingRecordingMessage({
            eventsRange: {
                start: lastTimestamp,
                end: lastTimestamp,
            },
            eventsByWindowId: {
                window_id_1: [
                    {
                        timestamp: lastTimestamp,
                        type: 4,
                        data: { href: 'http://localhost:3001/', width: 2560, height: 1304 },
                    },
                ],
            },
            metadata: {
                offset: 12344,
                timestamp: DateTime.now().minus({ milliseconds: flushThreshold }).toMillis(),
            } as any,
        })

        await sessionManager.add(eventOne)
        await sessionManager.add(eventTwo)

        await sessionManager.flushIfSessionBufferIsOld(now())

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

        await sessionManager.add(event)
        await sessionManager.flushIfSessionBufferIsOld(now.minus({ milliseconds: aDayInMilliseconds }).toMillis())

        // as a proxy for flush having been called or not
        expect(createReadStream).not.toHaveBeenCalled()
    })

    it('does flush if lagging but nonetheless too old', async () => {
        const aDayInMilliseconds = 24 * 60 * 60 * 1000
        const now = DateTime.now()

        // Create an event that is a little more than a day old
        const event = createIncomingRecordingMessage({
            metadata: {
                timestamp: now.minus({ milliseconds: aDayInMilliseconds - 3500 }).toMillis(),
            } as any,
        })

        await sessionManager.add(event)
        await sessionManager.flushIfSessionBufferIsOld(now.minus({ milliseconds: aDayInMilliseconds }).toMillis())
        expect(createReadStream).not.toHaveBeenCalled()

        // Manually modify the date to simulate this being idle for too long
        // This triggers the "memory" flush
        sessionManager.buffer.createdAt = now
            .minus({ milliseconds: flushThreshold * defaultConfig.SESSION_RECORDING_BUFFER_AGE_IN_MEMORY_MULTIPLIER })
            .toMillis()
        await sessionManager.flushIfSessionBufferIsOld(now.minus({ milliseconds: aDayInMilliseconds }).toMillis())
        expect(createReadStream).toHaveBeenCalled()
    })

    it('flushes messages', async () => {
        const event = createIncomingRecordingMessage()
        await sessionManager.add(event)
        expect(sessionManager.buffer.count).toEqual(1)
        const fileStream = sessionManager.buffer.fileStream
        const afterResumeFlushPromise = sessionManager.flush('buffer_size')

        expect(sessionManager.buffer.count).toEqual(0)
        expect(sessionManager.flushBuffer?.count).toEqual(1)

        await afterResumeFlushPromise

        expect(sessionManager.flushBuffer).toEqual(undefined)
        expect(fileStream.end).toHaveBeenCalledTimes(2) // One for the write, one for the destroy
    })

    it('flushes messages and whilst collecting new ones', async () => {
        const event = createIncomingRecordingMessage()
        const event2 = createIncomingRecordingMessage({
            eventsByWindowId: { window_id_1: [{ timestamp: 1234, type: 4, data: { href: 'http://localhost:3001/' } }] },
        })
        await sessionManager.add(event)
        expect(sessionManager.buffer.count).toEqual(1)

        const firstBufferFile = sessionManager.buffer.file('gz')
        const flushPromise = sessionManager.flush('buffer_size')
        await sessionManager.add(event2)

        // that the second event is in a new buffer file
        // that the original buffer file is deleted
        expect(sessionManager.buffer.file('gz')).not.toEqual(firstBufferFile)

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
            'utf-8',
        ])
    })

    it('tracks the offsets', async () => {
        const addEvent = (offset: number) =>
            sessionManager.add(
                createIncomingRecordingMessage({
                    metadata: {
                        lowOffset: offset,
                        highOffset: offset,
                    } as any,
                })
            )

        await addEvent(4)

        expect(sessionManager.buffer.offsets).toEqual({
            highest: 4,
            lowest: 4,
        })

        await addEvent(10)

        expect(sessionManager.buffer.offsets).toEqual({
            highest: 10,
            lowest: 4,
        })

        await addEvent(2)

        expect(sessionManager.buffer.offsets).toEqual({
            highest: 10,
            lowest: 2,
        })
    })

    it('has a fixed jitter based on the serverConfig', () => {
        const minJitter = 1 - defaultConfig.SESSION_RECORDING_BUFFER_AGE_JITTER
        for (const _ of Array(100).keys()) {
            const sm = createSessionManager()
            expect(sm.flushJitterMultiplier).toBeGreaterThanOrEqual(minJitter)
            expect(sm.flushJitterMultiplier).toBeLessThanOrEqual(1)
        }
    })

    // it('waits for the drain if write returns false', async () => {
    //     await sessionManager.add(createIncomingRecordingMessage())
    //     ;(sessionManager.buffer.fileStream.write as jest.Mock).mockReturnValueOnce(false)
    //     await sessionManager.add(createIncomingRecordingMessage())

    //     expect(sessionManager.buffer.fileStream.once).toHaveBeenCalledWith('drain', expect.any(Function))
    // })
})

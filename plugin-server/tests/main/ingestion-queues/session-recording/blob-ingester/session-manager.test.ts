import { createReadStream, writeFileSync } from 'fs'
import { appendFile, unlink } from 'fs/promises'
import { DateTime, Settings } from 'luxon'

import { defaultConfig } from '../../../../../src/config/config'
import { SessionManager } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/session-manager'
import { compressToString } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/utils'
import { createChunkedIncomingRecordingMessage, createIncomingRecordingMessage } from '../fixtures'

jest.mock('fs', () => {
    return {
        ...jest.requireActual('fs'),
        writeFileSync: jest.fn(),
        createReadStream: jest.fn(),
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
        })

        // the buffer file was created
        expect(writeFileSync).toHaveBeenCalledWith(sessionManager.buffer.file, '', 'utf-8')
    })

    it('tracks buffer age span', async () => {
        const firstMessageTimestamp = DateTime.now().toMillis() - 10000
        const secondMessageTimestamp = DateTime.now().toMillis() - 5000

        const payload = JSON.stringify([{ simple: 'data' }])
        const event = createIncomingRecordingMessage({
            data: compressToString(payload),
        })

        event.metadata.timestamp = firstMessageTimestamp
        await sessionManager.add(event)

        event.metadata.timestamp = secondMessageTimestamp
        await sessionManager.add(event)

        expect(sessionManager.buffer).toEqual({
            count: 2,
            oldestKafkaTimestamp: firstMessageTimestamp,
            file: expect.any(String),
            id: expect.any(String),
            size: 61 * 2, // The size of the event payload - this may change when test data changes
            offsets: [1, 1],
        })
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
        const payload = JSON.stringify([{ simple: 'data' }])
        const event = createIncomingRecordingMessage({
            data: compressToString(payload),
        })

        const flushThreshold = 2500 // any value here...
        event.metadata.timestamp = DateTime.now().minus({ milliseconds: flushThreshold }).toMillis()
        await sessionManager.add(event)

        await sessionManager.flushIfSessionBufferIsOld(DateTime.now().toMillis(), flushThreshold)

        // as a proxy for flush having been called or not
        expect(createReadStream).toHaveBeenCalled()
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
})

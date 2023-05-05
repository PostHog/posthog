import { DateTime } from 'luxon'
import fs from 'node:fs'

import { defaultConfig } from '../../../../../src/config/config'
import { SessionManager } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/session-manager'
import { compressToString } from '../../../../../src/main/ingestion-queues/session-recording/blob-ingester/utils'
import { createChunkedIncomingRecordingMessage, createIncomingRecordingMessage } from '../fixtures'

describe('session-manager', () => {
    let sessionManager: SessionManager
    const mockFinish = jest.fn()
    const mockS3Client: any = {
        send: jest.fn(),
    }

    beforeEach(() => {
        sessionManager = new SessionManager(defaultConfig, mockS3Client, 1, 'session_id_1', 1, 'topic', mockFinish)
        mockFinish.mockClear()
    })

    it('adds a message', async () => {
        const payload = JSON.stringify([{ simple: 'data' }])
        const event = createIncomingRecordingMessage({
            data: compressToString(payload),
        })
        const messageTimestamp = DateTime.local().toMillis()
        event.metadata.timestamp = messageTimestamp
        await sessionManager.add(event)

        expect(sessionManager.buffer).toEqual({
            count: 1,
            createdAt: expect.any(Date),
            lastMessageReceivedAt: messageTimestamp,
            file: expect.any(String),
            id: expect.any(String),
            size: 61, // The size of the event payload - this may change when test data changes
            offsets: [1],
        })
        const fileContents = JSON.parse(fs.readFileSync(sessionManager.buffer.file, 'utf-8'))
        expect(fileContents.data).toEqual(payload)
    })

    it('does not flush if it has received a message recently', async () => {
        const payload = JSON.stringify([{ simple: 'data' }])
        const event = createIncomingRecordingMessage({
            data: compressToString(payload),
        })
        event.metadata.timestamp = DateTime.local().minus({ minutes: 9 }).toMillis()
        await sessionManager.add(event)

        await sessionManager.flushIfSessionIsIdle()

        expect(sessionManager.buffer.count).toEqual(1)
    })

    it('does not flush if it has not received a message recently', async () => {
        const payload = JSON.stringify([{ simple: 'data' }])
        const event = createIncomingRecordingMessage({
            data: compressToString(payload),
        })
        event.metadata.timestamp = DateTime.local().minus({ minutes: 11 }).toMillis()
        await sessionManager.add(event)

        await sessionManager.flushIfSessionIsIdle()

        expect(sessionManager.buffer.count).toEqual(0)
    })

    it('flushes messages', async () => {
        const event = createIncomingRecordingMessage()
        await sessionManager.add(event)
        expect(sessionManager.buffer.count).toEqual(1)
        const file = sessionManager.buffer.file
        expect(fs.existsSync(file)).toEqual(true)

        const afterResumeFlushPromise = sessionManager.flush()

        expect(sessionManager.buffer.count).toEqual(0)
        expect(sessionManager.flushBuffer?.count).toEqual(1)

        await afterResumeFlushPromise

        expect(sessionManager.flushBuffer).toEqual(undefined)
        expect(mockFinish).toBeCalledTimes(1)
        expect(fs.existsSync(file)).toEqual(false)
    })

    it('flushes messages and whilst collecting new ones', async () => {
        const event = createIncomingRecordingMessage()
        const event2 = createIncomingRecordingMessage()
        await sessionManager.add(event)
        expect(sessionManager.buffer.count).toEqual(1)

        const flushPromise = sessionManager.flush()
        await sessionManager.add(event2)

        expect(sessionManager.buffer.count).toEqual(1)
        expect(sessionManager.flushBuffer?.count).toEqual(1)

        await flushPromise

        expect(sessionManager.flushBuffer).toEqual(undefined)
        expect(sessionManager.buffer.count).toEqual(1)
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

        const fileContents = JSON.parse(fs.readFileSync(sessionManager.buffer.file, 'utf-8'))
        expect(fileContents.data).toEqual('[{"simple":"data"}]')
    })
})

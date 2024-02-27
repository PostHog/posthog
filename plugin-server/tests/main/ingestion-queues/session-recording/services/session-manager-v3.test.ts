import { Upload } from '@aws-sdk/lib-storage'
import { randomUUID } from 'crypto'
import fs from 'fs/promises'
import { DateTime, Settings } from 'luxon'
import path from 'path'
import { PassThrough } from 'stream'
import * as zlib from 'zlib'

import { defaultConfig } from '../../../../../src/config/config'
import { SessionManagerV3 } from '../../../../../src/main/ingestion-queues/session-recording/services/session-manager-v3'
import { now } from '../../../../../src/main/ingestion-queues/session-recording/utils'
import { createIncomingRecordingMessage } from '../fixtures'

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

const tmpDir = path.join(__dirname, '../../../../../.tmp/test_session_recordings')

describe('session-manager', () => {
    jest.setTimeout(1000)
    let sessionManager: SessionManagerV3
    const mockS3Client: any = {
        send: jest.fn(),
    }

    const createSessionManager = async (
        sessionId = randomUUID(),
        teamId = 1,
        partition = 1
    ): Promise<SessionManagerV3> => {
        return await SessionManagerV3.create(defaultConfig, mockS3Client, {
            sessionId,
            teamId,
            partition,
            dir: path.join(tmpDir, `${partition}`, `${teamId}__${sessionId}`),
        })
    }

    const flushThreshold = defaultConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS * 1000

    beforeEach(async () => {
        // it's always May 25
        Settings.now = () => new Date(2018, 4, 25).valueOf()

        if (await fs.stat(tmpDir).catch(() => null)) {
            await fs.rmdir(tmpDir, { recursive: true })
        }

        sessionManager = await createSessionManager()
    })

    afterEach(async () => {
        await sessionManager?.stop()
        // it's no longer always May 25
        Settings.now = () => new Date().valueOf()
    })

    it('adds a message', async () => {
        const timestamp = now()
        const event = createIncomingRecordingMessage({
            events: [
                { timestamp: timestamp, type: 4, data: { href: 'http://localhost:3001/' } },
                { timestamp: timestamp + 1000, type: 4, data: { href: 'http://localhost:3001/' } },
            ],
        })

        await sessionManager.add(event)

        expect(sessionManager.buffer?.context).toEqual({
            sizeEstimate: 193,
            count: 1,
            eventsRange: { firstTimestamp: timestamp, lastTimestamp: timestamp + 1000 },
            createdAt: timestamp,
        })

        const stats = await fs.stat(`${sessionManager.context.dir}/buffer.jsonl`)
        expect(stats.size).toBeGreaterThan(0)
    })

    it('does not flush if it has received a message recently', async () => {
        const now = DateTime.now()

        const event = createIncomingRecordingMessage({
            metadata: {
                timestamp: now,
            } as any,
        })

        await sessionManager.add(event)
        await sessionManager.flush()

        expect(await fs.readdir(sessionManager.context.dir)).toEqual(['buffer.jsonl', 'metadata.json'])
    })

    it('does flush if the stored file is older than the threshold', async () => {
        const firstTimestamp = 1700000000000
        const lastTimestamp = 1700000000000 + 4000

        const eventOne = createIncomingRecordingMessage({
            events: [{ timestamp: firstTimestamp, type: 4, data: { href: 'http://localhost:3001/' } }],
        })
        const eventTwo = createIncomingRecordingMessage({
            events: [{ timestamp: lastTimestamp, type: 4, data: { href: 'http://localhost:3001/' } }],
        })

        await sessionManager.add(eventOne)
        await sessionManager.add(eventTwo)

        sessionManager.buffer!.context.createdAt = now() - flushThreshold - 1

        await sessionManager.flush()

        expect(await fs.readdir(sessionManager.context.dir)).toEqual([])

        const sessionId = sessionManager.context.sessionId

        // as a proxy for flush having been called or not
        const mockUploadCalls = (Upload as unknown as jest.Mock).mock.calls
        expect(mockUploadCalls.length).toBe(1)
        expect(mockUploadCalls[0].length).toBe(1)
        expect(mockUploadCalls[0][0]).toEqual(
            expect.objectContaining({
                params: expect.objectContaining({
                    Key: `session_recordings/team_id/1/session_id/${sessionId}/data/${firstTimestamp}-${lastTimestamp}.jsonl`,
                }),
            })
        )
    })

    it('has a fixed jitter based on the serverConfig', async () => {
        const minJitter = 1 - defaultConfig.SESSION_RECORDING_BUFFER_AGE_JITTER
        for (const _ of Array(100).keys()) {
            const sm = await createSessionManager()
            expect(sm.flushJitterMultiplier).toBeGreaterThanOrEqual(minJitter)
            expect(sm.flushJitterMultiplier).toBeLessThanOrEqual(1)
        }
    })

    it('not remove files when stopped', async () => {
        expect(await fs.readdir(sessionManager.context.dir)).toEqual([])
        await sessionManager.add(createIncomingRecordingMessage())
        expect(await fs.readdir(sessionManager.context.dir)).toEqual(['buffer.jsonl', 'metadata.json'])
        await sessionManager.stop()
        expect(await fs.readdir(sessionManager.context.dir)).toEqual(['buffer.jsonl', 'metadata.json'])
    })

    it('removes the directly when stopped after fully flushed', async () => {
        const sm = await createSessionManager('session_id_2', 2, 2)
        expect(await fs.readdir(sm.context.dir)).toEqual([])
        await sm.add(createIncomingRecordingMessage())
        expect(await fs.readdir(sm.context.dir)).toEqual(['buffer.jsonl', 'metadata.json'])
        await sm.flush(true)
        expect(await fs.readdir(sm.context.dir)).toEqual([])
        await sm.stop()
        // ;(sessionManager as any) = undefined // Stop the afterEach from failing

        await expect(fs.stat(sm.context.dir)).rejects.toThrowError('ENOENT: no such file or directory')
    })

    it('reads successfully with the stream not closed', async () => {
        const event = createIncomingRecordingMessage({
            events: [
                { timestamp: 170000000, type: 4, data: { href: 'http://localhost:3001/' } },
                { timestamp: 170000000 + 1000, type: 4, data: { href: 'http://localhost:3001/' } },
            ],
        })
        await sessionManager.add(event)

        const content = await fs.readFile(`${sessionManager.context.dir}/buffer.jsonl`, 'utf-8')
        expect(content).toEqual(
            '{"window_id":"window_id_1","data":[{"timestamp":170000000,"type":4,"data":{"href":"http://localhost:3001/"}},{"timestamp":170001000,"type":4,"data":{"href":"http://localhost:3001/"}}]}\n'
        )
    })

    it('adds to the existing buffer when restarted', async () => {
        const sm1 = await createSessionManager('session_id_2', 2, 2)

        await sm1.add(
            createIncomingRecordingMessage({
                events: [
                    { timestamp: 170000000, type: 4, data: { href: 'http://localhost:3001/' } },
                    { timestamp: 170000000 + 1000, type: 4, data: { href: 'http://localhost:3001/' } },
                ],
            })
        )

        const sm2 = await createSessionManager('session_id_2', 2, 2)
        await sm2.add(
            createIncomingRecordingMessage({
                events: [
                    { timestamp: 170000000 + 2000, type: 4, data: { href: 'http://localhost:3001/' } },
                    { timestamp: 170000000 + 3000, type: 4, data: { href: 'http://localhost:3001/' } },
                ],
            })
        )

        const buffer = await fs.readFile(`${sm1.context.dir}/buffer.jsonl`, 'utf-8')
        expect(buffer).toEqual(
            '{"window_id":"window_id_1","data":[{"timestamp":170000000,"type":4,"data":{"href":"http://localhost:3001/"}},{"timestamp":170001000,"type":4,"data":{"href":"http://localhost:3001/"}}]}\n{"window_id":"window_id_1","data":[{"timestamp":170002000,"type":4,"data":{"href":"http://localhost:3001/"}},{"timestamp":170003000,"type":4,"data":{"href":"http://localhost:3001/"}}]}\n'
        )

        await sm1.stop()
        await sm2.stop()
    })

    it('uploads a gzip compressed file to S3', async () => {
        await sessionManager.add(
            createIncomingRecordingMessage({
                events: [{ timestamp: 170000000, type: 4, data: { href: 'http://localhost:3001/' } }],
            })
        )
        await sessionManager.flush(true)

        const mockUploadCalls = (Upload as unknown as jest.Mock).mock.calls
        expect(mockUploadCalls[0][0]).toMatchObject({
            params: {
                Bucket: 'posthog',
                Key: `session_recordings/team_id/1/session_id/${sessionManager.context.sessionId}/data/170000000-170000000.jsonl`,
                ContentEncoding: 'gzip',
                ContentType: 'application/jsonl',
            },
        })
        const uploadBody = mockUploadCalls[0][0].params.Body

        expect(uploadBody).toBeInstanceOf(PassThrough)

        // Extract the content from the stream and gzip decompress it
        const chunks: Uint8Array[] = []
        for await (const chunk of uploadBody) {
            chunks.push(chunk)
        }

        const buffer = Buffer.concat(chunks)
        const uncompressed = zlib.gunzipSync(buffer).toString('utf-8')

        expect(uncompressed).toEqual(
            '{"window_id":"window_id_1","data":[{"timestamp":170000000,"type":4,"data":{"href":"http://localhost:3001/"}}]}\n'
        )
    })
})

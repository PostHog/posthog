/**
 * Integration tests for the session recording batch file format
 *
 * The batch file format is a sequence of independently-readable session blocks:
 * ```
 * Session Batch File
 * ├── Snappy Session Recording Block 1
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       ├── [windowId, event2]
 * │       └── ...
 * ├── Snappy Session Recording Block 2
 * │   └── JSONL Session Recording Block
 * │       ├── [windowId, event1]
 * │       └── ...
 * └── ...
 * ```
 *
 * Each session block:
 * - Contains all events for one session recording
 * - Is compressed independently with Snappy
 * - Can be read in isolation using the block metadata (offset and length)
 * - Contains newline-delimited JSON records after decompression
 * - Each record is an array of [windowId, event]
 */

import snappy from 'snappy'
import { PassThrough } from 'stream'

import { KafkaOffsetManager } from '../kafka/offset-manager'
import { MessageWithTeam } from '../teams/types'
import { SessionBatchFileWriter } from './session-batch-file-writer'
import { SessionBatchRecorder, SessionBlockMetadata } from './session-batch-recorder'

const enum EventType {
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
}

describe('session recording integration', () => {
    let recorder: SessionBatchRecorder
    let mockOffsetManager: jest.Mocked<KafkaOffsetManager>
    let mockWriter: jest.Mocked<SessionBatchFileWriter>
    let mockStream: PassThrough
    let mockFinish: jest.Mock

    beforeEach(() => {
        mockStream = new PassThrough()
        mockFinish = jest.fn().mockResolvedValue(undefined)
        mockWriter = {
            newBatch: jest.fn().mockReturnValue({ stream: mockStream, finish: mockFinish }),
        } as unknown as jest.Mocked<SessionBatchFileWriter>

        mockOffsetManager = {
            trackOffset: jest.fn(),
            discardPartition: jest.fn(),
            commit: jest.fn(),
        } as unknown as jest.Mocked<KafkaOffsetManager>

        recorder = new SessionBatchRecorder(mockOffsetManager, mockWriter)
    })

    const createMessage = (
        sessionId: string,
        teamId: number,
        events: { type: EventType; data: any }[]
    ): MessageWithTeam => ({
        team: {
            teamId,
            consoleLogIngestionEnabled: false,
        },
        message: {
            distinct_id: 'distinct_id',
            session_id: sessionId,
            eventsByWindowId: {
                window1: events.map((event, index) => ({
                    ...event,
                    timestamp: 1000 + index * 1000,
                })),
            },
            eventsRange: {
                start: 1000,
                end: 1000 + (events.length - 1) * 1000,
            },
            metadata: {
                partition: 1,
                topic: 'test',
                offset: 0,
                timestamp: 0,
                rawSize: 0,
            },
        },
    })

    const readSessionFromBatch = async (
        batchBuffer: Buffer,
        blockMetadata: SessionBlockMetadata
    ): Promise<[string, any][]> => {
        const sessionBuffer = batchBuffer.subarray(
            blockMetadata.blockStartOffset,
            blockMetadata.blockStartOffset + blockMetadata.blockLength
        )
        const decompressed = await snappy.uncompress(sessionBuffer)
        return decompressed
            .toString()
            .trim()
            .split('\n')
            .map((line) => JSON.parse(line))
    }

    it('should correctly record and read back multiple sessions', async () => {
        const messages = [
            createMessage('session1', 42, [
                { type: EventType.FullSnapshot, data: { source: 1, snapshot: { html: '<div>1</div>' } } },
                { type: EventType.IncrementalSnapshot, data: { source: 2, mutations: [{ id: 1 }] } },
            ]),
            createMessage('session2', 787, [
                { type: EventType.Meta, data: { href: 'https://example.com', width: 1024, height: 768 } },
                { type: EventType.FullSnapshot, data: { source: 1, snapshot: { html: '<div>2</div>' } } },
            ]),
            createMessage('session3', 123, [
                { type: EventType.FullSnapshot, data: { source: 1, snapshot: { html: '<div>3</div>' } } },
                { type: EventType.IncrementalSnapshot, data: { source: 3, mousemove: [{ x: 100, y: 200 }] } },
                { type: EventType.Meta, data: { href: 'https://example.com/page2' } },
            ]),
        ]

        // Record all messages
        messages.forEach((message) => recorder.record(message))

        // Collect the output stream data
        const streamDataPromise = new Promise<Buffer>((resolve) => {
            const chunks: Buffer[] = []
            mockStream.on('data', (chunk) => chunks.push(chunk))
            mockStream.on('end', () => resolve(Buffer.concat(chunks)))
        })

        // Flush and get metadata
        const metadata = await recorder.flush()
        const batchBuffer = await streamDataPromise

        // Verify we got all sessions
        expect(metadata).toHaveLength(3)
        expect(new Set(metadata.map((block) => block.sessionId))).toEqual(new Set(['session1', 'session2', 'session3']))

        // Read and verify each session's data
        for (const block of metadata) {
            const events = await readSessionFromBatch(batchBuffer, block)
            const originalMessage = messages.find((m) => m.message.session_id === block.sessionId)!
            const originalEvents = originalMessage.message.eventsByWindowId.window1

            expect(block.teamId).toBe(originalMessage.team.teamId)
            expect(events).toHaveLength(originalEvents.length)

            events.forEach(([windowId, event], index) => {
                expect(windowId).toBe('window1')
                expect(event.type).toBe(originalEvents[index].type)
                expect(event.data).toEqual(originalEvents[index].data)
            })
        }

        // Verify the batch was properly finalized
        expect(mockFinish).toHaveBeenCalled()
        expect(mockOffsetManager.commit).toHaveBeenCalled()
    })
})

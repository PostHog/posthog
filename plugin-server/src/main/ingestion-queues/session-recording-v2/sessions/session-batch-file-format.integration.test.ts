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
import { DateTime } from 'luxon'
import snappy from 'snappy'

import { parseJSON } from '../../../../utils/json-parse'
import { KafkaOffsetManager } from '../kafka/offset-manager'
import { MessageWithTeam } from '../teams/types'
import { SessionBatchFileStorage, SessionBatchFileWriter, WriteSessionData } from './session-batch-file-storage'
import { SessionBatchRecorder } from './session-batch-recorder'
import { SessionBlockMetadata } from './session-block-metadata'
import { SessionConsoleLogStore } from './session-console-log-store'
import { SessionMetadataStore } from './session-metadata-store'

const enum EventType {
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
}

describe('session recording integration', () => {
    let recorder: SessionBatchRecorder
    let mockOffsetManager: jest.Mocked<KafkaOffsetManager>
    let mockStorage: jest.Mocked<SessionBatchFileStorage>
    let mockWriter: jest.Mocked<SessionBatchFileWriter>
    let mockMetadataStore: jest.Mocked<SessionMetadataStore>
    let mockConsoleLogStore: jest.Mocked<SessionConsoleLogStore>
    let batchBuffer: Uint8Array
    let currentOffset: number

    beforeEach(() => {
        currentOffset = 0
        batchBuffer = new Uint8Array()

        mockWriter = {
            writeSession: jest.fn().mockImplementation(async (sessionData: WriteSessionData) => {
                const buffer = sessionData.buffer
                const startOffset = currentOffset
                const newBuffer = new Uint8Array(batchBuffer.length + buffer.length)
                newBuffer.set(batchBuffer)
                newBuffer.set(new Uint8Array(buffer), batchBuffer.length)
                batchBuffer = newBuffer
                currentOffset += buffer.length
                return Promise.resolve({
                    bytesWritten: buffer.length,
                    url: `test-url?range=bytes=${startOffset}-${currentOffset - 1}`,
                    retentionPeriod: null,
                })
            }),
            finish: jest.fn().mockResolvedValue(undefined),
        }

        mockStorage = {
            newBatch: jest.fn().mockReturnValue(mockWriter),
            checkHealth: jest.fn().mockResolvedValue(true),
        } as jest.Mocked<SessionBatchFileStorage>

        mockOffsetManager = {
            trackOffset: jest.fn(),
            discardPartition: jest.fn(),
            commit: jest.fn(),
        } as unknown as jest.Mocked<KafkaOffsetManager>

        mockMetadataStore = {
            storeSessionBlocks: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionMetadataStore>

        mockConsoleLogStore = {
            storeSessionConsoleLogs: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionConsoleLogStore>

        recorder = new SessionBatchRecorder(
            mockOffsetManager,
            mockStorage,
            mockMetadataStore,
            mockConsoleLogStore,
            new Date('2025-01-01T10:00:00.000Z')
        )
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
                    timestamp: DateTime.fromISO('2025-01-01T10:00:00.000Z')
                        .plus({ seconds: index * 2 })
                        .toMillis(),
                })),
            },
            eventsRange: {
                start: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                end: DateTime.fromISO('2025-01-01T10:00:00.000Z').plus({
                    seconds: (events.length - 1) * 2,
                }),
            },
            metadata: {
                partition: 1,
                topic: 'test',
                offset: 0,
                timestamp: 0,
                rawSize: 0,
            },
            snapshot_source: null,
            snapshot_library: null,
        },
    })

    const readSessionFromBatch = async (blockMetadata: SessionBlockMetadata): Promise<[string, any][]> => {
        // Extract the byte range from the URL
        const match = blockMetadata.blockUrl?.match(/bytes=(\d+)-(\d+)/)
        if (!match) {
            throw new Error('Invalid block URL format')
        }
        const startOffset = parseInt(match[1])
        const endOffset = parseInt(match[2])

        const sessionBuffer = Buffer.from(batchBuffer.subarray(startOffset, endOffset + 1))
        const decompressed = await snappy.uncompress(sessionBuffer)
        return decompressed
            .toString()
            .trim()
            .split('\n')
            .map((line) => parseJSON(line))
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
        for (const message of messages) {
            await recorder.record(message)
        }

        // Flush and get metadata
        const metadata = await recorder.flush()

        // Verify we got all sessions
        expect(metadata).toHaveLength(3)
        expect(new Set(metadata.map((block) => block.sessionId))).toEqual(new Set(['session1', 'session2', 'session3']))

        // Read and verify each session's data
        for (const block of metadata) {
            const events = await readSessionFromBatch(block)
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
        expect(mockWriter.finish).toHaveBeenCalled()
        expect(mockOffsetManager.commit).toHaveBeenCalled()
        expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledWith(metadata)
    })
})

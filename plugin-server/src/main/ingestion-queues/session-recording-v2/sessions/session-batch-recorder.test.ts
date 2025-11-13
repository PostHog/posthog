import { DateTime } from 'luxon'
import { validate as uuidValidate } from 'uuid'

import { parseJSON } from '../../../../utils/json-parse'
import { KafkaOffsetManager } from '../kafka/offset-manager'
import { ParsedMessageData } from '../kafka/types'
import { SnapshotEvent } from '../kafka/types'
import { MessageWithTeam } from '../teams/types'
import { SessionBatchMetrics } from './metrics'
import { SessionBatchFileStorage, SessionBatchFileWriter } from './session-batch-file-storage'
import { SessionBatchRecorder } from './session-batch-recorder'
import { SessionConsoleLogRecorder } from './session-console-log-recorder'
import { SessionConsoleLogStore } from './session-console-log-store'
import { SessionMetadataStore } from './session-metadata-store'
import { EndResult, SnappySessionRecorder } from './snappy-session-recorder'

// RRWeb event type constants
const enum EventType {
    DomContentLoaded = 0,
    Load = 1,
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
    Custom = 5,
}

interface RRWebEvent {
    type: EventType
    timestamp: number
    data: Record<string, any>
}

interface MessageMetadata {
    partition?: number
    topic?: string
    offset?: number
    timestamp?: number
    rawSize?: number
}

export class SnappySessionRecorderMock {
    private chunks: Buffer[] = []
    private size: number = 0
    private startDateTime: DateTime | null = null
    private endDateTime: DateTime | null = null
    private _distinctId: string | null = null

    constructor(
        public readonly sessionId: string,
        public readonly teamId: number,
        private readonly batchId: string
    ) {}

    public recordMessage(message: ParsedMessageData): number {
        let bytesWritten = 0

        // Store distinctId from first message
        if (!this._distinctId) {
            this._distinctId = message.distinct_id
        }

        if (!this.startDateTime || message.eventsRange.start < this.startDateTime) {
            this.startDateTime = message.eventsRange.start
        }
        if (!this.endDateTime || message.eventsRange.end > this.endDateTime) {
            this.endDateTime = message.eventsRange.end
        }

        Object.entries(message.eventsByWindowId).forEach(([windowId, events]) => {
            events.forEach((event) => {
                const serializedLine = JSON.stringify([windowId, event]) + '\n'
                this.chunks.push(Buffer.from(serializedLine))
                bytesWritten += Buffer.byteLength(serializedLine)
            })
        })

        this.size += bytesWritten
        return bytesWritten
    }

    public get distinctId(): string {
        if (!this._distinctId) {
            throw new Error('No distinct_id set. No messages recorded yet.')
        }
        return this._distinctId
    }

    public end(): EndResult {
        const buffer = Buffer.concat(this.chunks as any[])
        return {
            buffer,
            eventCount: this.chunks.length,
            startDateTime: this.startDateTime ?? DateTime.now(),
            endDateTime: this.endDateTime ?? DateTime.now(),
            firstUrl: null,
            urls: [],
            clickCount: 0,
            keypressCount: 0,
            mouseActivityCount: 0,
            activeMilliseconds: 0,
            size: buffer.length,
            messageCount: 0,
            snapshotSource: null,
            snapshotLibrary: null,
            batchId: this.batchId,
        }
    }
}

jest.mock('./session-console-log-recorder', () => ({
    SessionConsoleLogRecorder: jest.fn().mockImplementation((_sessionId, _teamId, _batchId) => ({
        recordMessage: jest.fn().mockResolvedValue(undefined),
        end: jest.fn().mockReturnValue({
            consoleLogCount: 3,
            consoleWarnCount: 2,
            consoleErrorCount: 1,
        }),
    })),
}))

jest.setTimeout(1000)

jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementBatchesFlushed: jest.fn(),
        incrementSessionsFlushed: jest.fn(),
        incrementEventsFlushed: jest.fn(),
        incrementBytesWritten: jest.fn(),
        incrementSessionsRateLimited: jest.fn(),
        incrementEventsRateLimited: jest.fn(),
    },
}))

jest.mock('./blackhole-session-batch-writer')
jest.mock('./snappy-session-recorder', () => ({
    SnappySessionRecorder: jest
        .fn()
        .mockImplementation(
            (sessionId: string, teamId: number, batchId: string) =>
                new SnappySessionRecorderMock(sessionId, teamId, batchId)
        ),
}))

describe('SessionBatchRecorder', () => {
    let recorder: SessionBatchRecorder
    let mockOffsetManager: jest.Mocked<KafkaOffsetManager>
    let mockWriter: jest.Mocked<SessionBatchFileWriter>
    let mockStorage: jest.Mocked<SessionBatchFileStorage>
    let mockMetadataStore: jest.Mocked<SessionMetadataStore>
    let mockConsoleLogStore: jest.Mocked<SessionConsoleLogStore>

    beforeEach(() => {
        jest.clearAllMocks()

        jest.mocked(SnappySessionRecorder).mockImplementation(
            (sessionId: string, teamId: number, batchId: string) =>
                new SnappySessionRecorderMock(sessionId, teamId, batchId) as unknown as SnappySessionRecorder
        )

        mockWriter = {
            writeSession: jest.fn().mockResolvedValue({
                bytesWritten: 100,
                url: 's3://test/file?range=bytes=0-99',
            }),
            finish: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionBatchFileWriter>

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

        mockStorage = {
            newBatch: jest.fn().mockReturnValue(mockWriter),
        } as unknown as jest.Mocked<SessionBatchFileStorage>

        recorder = new SessionBatchRecorder(
            mockOffsetManager,
            mockStorage,
            mockMetadataStore,
            mockConsoleLogStore,
            new Date('2025-01-02 00:00:00Z'),
            Number.MAX_SAFE_INTEGER
        )
    })

    const createMessage = (
        sessionId: string,
        events: SnapshotEvent[],
        metadata: MessageMetadata = {},
        teamId: number = 1,
        distinctId: string = 'distinct_id'
    ): MessageWithTeam => ({
        team: {
            teamId,
            consoleLogIngestionEnabled: false,
        },
        message: {
            distinct_id: distinctId,
            session_id: sessionId,
            eventsByWindowId: {
                window1: events,
            },
            eventsRange: {
                start: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                end: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
            },
            metadata: {
                partition: 1,
                topic: 'test',
                offset: 0,
                timestamp: 0,
                rawSize: 0,
                ...metadata,
            },
            snapshot_source: null,
            snapshot_library: null,
        },
    })

    const parseLines = (output: string): [string, RRWebEvent][] => {
        return output
            .trim()
            .split('\n')
            .map((line) => {
                const [windowId, event] = parseJSON(line)
                return [windowId, event]
            })
    }

    // Helper to capture written data
    const captureWrittenData = (mockWriteSession: jest.Mock): string[] => {
        return mockWriteSession.mock.calls.map(([data]) => data.buffer.toString())
    }

    describe('recording and writing', () => {
        it('should write events in correct format', async () => {
            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            await recorder.record(message)
            await recorder.flush()

            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)
            const lines = parseLines(writtenData[0])
            expect(lines).toEqual([['window1', message.message.eventsByWindowId.window1[0]]])
        })

        it('should process and flush a single session and track offsets', async () => {
            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1, adds: [{ parentId: 1, nextId: 2, node: { tag: 'div' } }] },
                },
            ])

            await recorder.record(message)
            expect(mockOffsetManager.trackOffset).toHaveBeenCalledWith({
                partition: message.message.metadata.partition,
                offset: message.message.metadata.offset,
            })

            await recorder.flush()
            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)

            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockOffsetManager.commit).toHaveBeenCalledTimes(1)

            const lines = parseLines(writtenData[0])
            expect(lines).toEqual([['window1', message.message.eventsByWindowId.window1[0]]])
        })

        it('should handle multiple sessions in parallel', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.Meta,
                        timestamp: DateTime.fromISO('2025-01-01T10:00:00.000Z').toMillis(),
                        data: { href: 'https://example.com' },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Custom,
                        timestamp: DateTime.fromISO('2025-01-01T10:00:01.000Z').toMillis(),
                        data: { tag: 'user-interaction' },
                    },
                ]),
            ]

            for (const message of messages) {
                await recorder.record(message)
                expect(mockOffsetManager.trackOffset).toHaveBeenCalledWith({
                    partition: message.message.metadata.partition,
                    offset: message.message.metadata.offset,
                })
            }
            expect(mockOffsetManager.trackOffset).toHaveBeenCalledTimes(2)

            await recorder.flush()

            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockOffsetManager.commit).toHaveBeenCalledTimes(1)

            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)
            const lines1 = parseLines(writtenData[0])
            const lines2 = parseLines(writtenData[1])
            expect(lines1).toEqual([['window1', messages[0].message.eventsByWindowId.window1[0]]])
            expect(lines2).toEqual([['window1', messages[1].message.eventsByWindowId.window1[0]]])
        })

        it('should accumulate events for the same session', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1, adds: [{ parentId: 1, nextId: 2, node: { tag: 'div' } }] },
                    },
                ]),
                createMessage('session1', [
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2, texts: [{ id: 1, value: 'Updated text' }] },
                    },
                ]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockOffsetManager.commit).toHaveBeenCalledTimes(1)

            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)
            const lines = parseLines(writtenData[0])
            expect(lines).toEqual([
                ['window1', messages[0].message.eventsByWindowId.window1[0]],
                ['window1', messages[1].message.eventsByWindowId.window1[0]],
            ])
        })

        it('should handle empty events array', async () => {
            const message = createMessage('session1', [])
            const bytesWritten = await recorder.record(message)

            await recorder.flush()

            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockOffsetManager.commit).toHaveBeenCalledTimes(1)

            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)
            expect(writtenData[0]).toBe('')
            expect(bytesWritten).toBe(0)
        })

        it('should group events by session when interleaved', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1, adds: [{ parentId: 1, nextId: 2, node: { tag: 'div' } }] },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Meta,
                        timestamp: 1100,
                        data: { href: 'https://example.com' },
                    },
                ]),
                createMessage('session1', [
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2, texts: [{ id: 1, value: 'Updated text' }] },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Custom,
                        timestamp: 2100,
                        data: { tag: 'user-interaction' },
                    },
                ]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockOffsetManager.commit).toHaveBeenCalledTimes(1)

            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)
            const lines1 = parseLines(writtenData[0])
            const lines2 = parseLines(writtenData[1])

            // Events should be grouped by session, maintaining chronological order within each session
            expect(lines1).toEqual([
                // All session1 events
                ['window1', messages[0].message.eventsByWindowId.window1[0]],
                ['window1', messages[2].message.eventsByWindowId.window1[0]],
            ])
            expect(lines2).toEqual([
                // All session2 events
                ['window1', messages[1].message.eventsByWindowId.window1[0]],
                ['window1', messages[3].message.eventsByWindowId.window1[0]],
            ])
        })

        it('should handle same session id with different teams as separate sessions', async () => {
            const messages = [
                createMessage(
                    'same_session_id',
                    [
                        {
                            type: EventType.FullSnapshot,
                            timestamp: 1000,
                            data: { source: 1 },
                        },
                    ],
                    {},
                    1,
                    'user1'
                ),
                createMessage(
                    'same_session_id',
                    [
                        {
                            type: EventType.Meta,
                            timestamp: 1100,
                            data: { href: 'https://example.com' },
                        },
                    ],
                    {},
                    2,
                    'user2'
                ),
                createMessage(
                    'same_session_id',
                    [
                        {
                            type: EventType.IncrementalSnapshot,
                            timestamp: 2000,
                            data: { source: 2 },
                        },
                    ],
                    {},
                    1,
                    'user1'
                ),
                createMessage(
                    'same_session_id',
                    [
                        {
                            type: EventType.Custom,
                            timestamp: 2100,
                            data: { tag: 'click' },
                        },
                    ],
                    {},
                    2,
                    'user2'
                ),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockOffsetManager.commit).toHaveBeenCalledTimes(1)

            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)
            const lines1 = parseLines(writtenData[0])
            const lines2 = parseLines(writtenData[1])

            // Events should be grouped by team ID despite having same session ID
            expect(lines1).toEqual([
                // All team 1 events
                ['window1', messages[0].message.eventsByWindowId.window1[0]],
                ['window1', messages[2].message.eventsByWindowId.window1[0]],
            ])
            expect(lines2).toEqual([
                // All team 2 events
                ['window1', messages[1].message.eventsByWindowId.window1[0]],
                ['window1', messages[3].message.eventsByWindowId.window1[0]],
            ])

            // Verify metadata store received separate session blocks for each team
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledWith(
                expect.arrayContaining([
                    expect.objectContaining({
                        sessionId: 'same_session_id',
                        teamId: 1,
                        distinctId: 'user1',
                    }),
                    expect.objectContaining({
                        sessionId: 'same_session_id',
                        teamId: 2,
                        distinctId: 'user2',
                    }),
                ])
            )
        })
    })

    describe('console log recording', () => {
        it('should create console log recorder for each session', async () => {
            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            await recorder.record(message)
            await recorder.flush()

            expect(SessionConsoleLogRecorder).toHaveBeenCalledWith(
                'session1',
                1,
                expect.any(String),
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z')
            )
            expect(jest.mocked(SessionConsoleLogRecorder).mock.results[0].value.recordMessage).toHaveBeenCalledWith(
                message
            )
        })

        it('should create console log recorder once per session', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1 },
                    },
                ]),
                createMessage('session1', [
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2 },
                    },
                ]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            expect(SessionConsoleLogRecorder).toHaveBeenCalledTimes(1)
            expect(SessionConsoleLogRecorder).toHaveBeenCalledWith(
                'session1',
                1,
                expect.any(String),
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z')
            )
            const mockRecorder = jest.mocked(SessionConsoleLogRecorder).mock.results[0].value
            expect(mockRecorder.recordMessage).toHaveBeenCalledTimes(2)
            expect(mockRecorder.recordMessage).toHaveBeenNthCalledWith(1, messages[0])
            expect(mockRecorder.recordMessage).toHaveBeenNthCalledWith(2, messages[1])
        })

        it('should create separate console log recorders for different sessions', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.Meta,
                        timestamp: DateTime.fromISO('2025-01-01T10:00:00.000Z').toMillis(),
                        data: { href: 'https://example.com' },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Custom,
                        timestamp: DateTime.fromISO('2025-01-01T10:00:01.000Z').toMillis(),
                        data: { tag: 'user-interaction' },
                    },
                ]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            expect(SessionConsoleLogRecorder).toHaveBeenCalledWith(
                'session1',
                1,
                expect.any(String),
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z')
            )
            expect(SessionConsoleLogRecorder).toHaveBeenCalledWith(
                'session2',
                1,
                expect.any(String),
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z')
            )
            expect(jest.mocked(SessionConsoleLogRecorder).mock.results[0].value.recordMessage).toHaveBeenCalledWith(
                messages[0]
            )
            expect(jest.mocked(SessionConsoleLogRecorder).mock.results[1].value.recordMessage).toHaveBeenCalledWith(
                messages[1]
            )
        })

        it('should flush console logs before storing metadata', async () => {
            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            let consoleLogFlushCalled = false
            let metadataStoreCalled = false

            mockConsoleLogStore.flush.mockImplementation(() => {
                expect(metadataStoreCalled).toBe(false)
                consoleLogFlushCalled = true
                return Promise.resolve()
            })

            mockMetadataStore.storeSessionBlocks.mockImplementation(() => {
                expect(consoleLogFlushCalled).toBe(true)
                metadataStoreCalled = true
                return Promise.resolve()
            })

            await recorder.record(message)
            await recorder.flush()

            expect(mockConsoleLogStore.flush).toHaveBeenCalledTimes(1)
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledTimes(1)
        })

        it('should correctly record messages for multiple interleaved sessions', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1 },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Meta,
                        timestamp: 1100,
                        data: { href: 'https://example.com' },
                    },
                ]),
                createMessage('session1', [
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2 },
                    },
                ]),
                createMessage('session3', [
                    {
                        type: EventType.Custom,
                        timestamp: 2100,
                        data: { tag: 'click' },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Meta,
                        timestamp: 3000,
                        data: { href: 'https://example.com/page2' },
                    },
                ]),
            ]

            // Record all messages
            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            // Verify recorder creation
            expect(SessionConsoleLogRecorder).toHaveBeenCalledTimes(3)
            expect(SessionConsoleLogRecorder).toHaveBeenCalledWith(
                'session1',
                1,
                expect.any(String),
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z')
            )
            expect(SessionConsoleLogRecorder).toHaveBeenCalledWith(
                'session2',
                1,
                expect.any(String),
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z')
            )
            expect(SessionConsoleLogRecorder).toHaveBeenCalledWith(
                'session3',
                1,
                expect.any(String),
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z')
            )

            // Get mock recorders
            const mockRecorders = jest.mocked(SessionConsoleLogRecorder).mock.results
            const session1Recorder = mockRecorders[0].value
            const session2Recorder = mockRecorders[1].value
            const session3Recorder = mockRecorders[2].value

            // Verify session1 recorder calls
            expect(session1Recorder.recordMessage).toHaveBeenCalledTimes(2)
            expect(session1Recorder.recordMessage).toHaveBeenNthCalledWith(1, messages[0])
            expect(session1Recorder.recordMessage).toHaveBeenNthCalledWith(2, messages[2])

            // Verify session2 recorder calls
            expect(session2Recorder.recordMessage).toHaveBeenCalledTimes(2)
            expect(session2Recorder.recordMessage).toHaveBeenNthCalledWith(1, messages[1])
            expect(session2Recorder.recordMessage).toHaveBeenNthCalledWith(2, messages[4])

            // Verify session3 recorder calls
            expect(session3Recorder.recordMessage).toHaveBeenCalledTimes(1)
            expect(session3Recorder.recordMessage).toHaveBeenCalledWith(messages[3])
        })

        it('should handle messages with different team IDs', async () => {
            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }], {}, 1),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }], {}, 1),
                createMessage('session2', [{ type: EventType.Meta, timestamp: 3000, data: {} }], {}, 2),
                createMessage('session2', [{ type: EventType.Meta, timestamp: 4000, data: {} }], {}, 2),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            // Verify recorder creation with correct team IDs
            expect(SessionConsoleLogRecorder).toHaveBeenCalledTimes(2)
            expect(SessionConsoleLogRecorder).toHaveBeenCalledWith(
                'session1',
                1,
                expect.any(String),
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z')
            )
            expect(SessionConsoleLogRecorder).toHaveBeenCalledWith(
                'session2',
                2,
                expect.any(String),
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z')
            )

            // Get mock recorders
            const mockRecorders = jest.mocked(SessionConsoleLogRecorder).mock.results
            const session1Recorder = mockRecorders[0].value
            const session2Recorder = mockRecorders[1].value

            // Verify correct message recording for each team
            expect(session1Recorder.recordMessage).toHaveBeenCalledTimes(2)
            expect(session1Recorder.recordMessage).toHaveBeenNthCalledWith(1, messages[0])
            expect(session1Recorder.recordMessage).toHaveBeenNthCalledWith(2, messages[1])

            expect(session2Recorder.recordMessage).toHaveBeenCalledTimes(2)
            expect(session2Recorder.recordMessage).toHaveBeenNthCalledWith(1, messages[2])
            expect(session2Recorder.recordMessage).toHaveBeenNthCalledWith(2, messages[3])
        })
    })

    describe('flushing behavior', () => {
        it('should clear sessions after flush', async () => {
            const message1 = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1, adds: [{ parentId: 1, nextId: 2, node: { tag: 'div' } }] },
                },
            ])

            await recorder.record(message1)
            await recorder.flush()

            const writtenData1 = captureWrittenData(mockWriter.writeSession as jest.Mock)
            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.flush).toHaveBeenCalledTimes(1)

            // Reset mock for second batch
            jest.clearAllMocks()
            mockStorage.newBatch.mockReturnValue(mockWriter)

            const message2 = createMessage('session1', [
                {
                    type: EventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 2, texts: [{ id: 1, value: 'Updated text' }] },
                },
            ])

            await recorder.record(message2)
            await recorder.flush()

            const writtenData2 = captureWrittenData(mockWriter.writeSession as jest.Mock)
            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.flush).toHaveBeenCalledTimes(1)

            const lines1 = parseLines(writtenData1[0])
            const lines2 = parseLines(writtenData2[0])
            expect(lines1).toEqual([['window1', message1.message.eventsByWindowId.window1[0]]])
            expect(lines2).toEqual([['window1', message2.message.eventsByWindowId.window1[0]]])
        })

        it('should not create file on second flush if no new events', async () => {
            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            await recorder.record(message)
            await recorder.flush()

            expect(mockStorage.newBatch).toHaveBeenCalledTimes(1)
            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.flush).toHaveBeenCalledTimes(1)

            // Second flush with no new events
            await recorder.flush()

            // Should not create a new batch or write any data
            expect(mockStorage.newBatch).toHaveBeenCalledTimes(1) // Only from first flush
            expect(mockWriter.finish).toHaveBeenCalledTimes(1) // Only from first flush
            expect(mockConsoleLogStore.flush).toHaveBeenCalledTimes(1) // Only from first flush

            // Should still commit offsets
            expect(mockOffsetManager.commit).toHaveBeenCalledTimes(2)
        })

        it('should not increment metrics when no events are flushed', async () => {
            await recorder.flush()

            // Should not create a new batch or write any data
            expect(mockStorage.newBatch).not.toHaveBeenCalled()
            expect(mockWriter.finish).not.toHaveBeenCalled()
            expect(mockMetadataStore.storeSessionBlocks).not.toHaveBeenCalled()
            expect(mockConsoleLogStore.flush).not.toHaveBeenCalled()

            // Should still commit offsets
            expect(mockOffsetManager.commit).toHaveBeenCalledTimes(1)

            // Should not increment any metrics
            expect(SessionBatchMetrics.incrementBatchesFlushed).not.toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementSessionsFlushed).not.toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementEventsFlushed).not.toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementBytesWritten).not.toHaveBeenCalled()
        })

        it('should store metadata after s3 write completes, but before offsets are committed', async () => {
            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            let finishCalled = false
            let metadataStoreCalled = false
            let consoleLogFlushCalled = false
            let commitCalled = false

            mockWriter.finish.mockImplementation(() => {
                finishCalled = true
                expect(metadataStoreCalled).toBe(false)
                expect(consoleLogFlushCalled).toBe(false)
                expect(commitCalled).toBe(false)
                return Promise.resolve()
            })

            mockConsoleLogStore.flush.mockImplementation(() => {
                expect(finishCalled).toBe(true)
                expect(metadataStoreCalled).toBe(false)
                expect(commitCalled).toBe(false)
                consoleLogFlushCalled = true
                return Promise.resolve()
            })

            mockMetadataStore.storeSessionBlocks.mockImplementation(() => {
                expect(consoleLogFlushCalled).toBe(true)
                expect(commitCalled).toBe(false)
                metadataStoreCalled = true
                return Promise.resolve()
            })

            mockOffsetManager.commit.mockImplementation(() => {
                expect(metadataStoreCalled).toBe(true)
                expect(commitCalled).toBe(false)
                commitCalled = true
                return Promise.resolve()
            })

            await recorder.record(message)
            await recorder.flush()

            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.flush).toHaveBeenCalledTimes(1)
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledTimes(1)
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledWith([
                expect.objectContaining({
                    sessionId: 'session1',
                    teamId: 1,
                    distinctId: 'distinct_id',
                    startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                    endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                    blockUrl: 's3://test/file?range=bytes=0-99',
                    blockLength: 100,
                    firstUrl: null,
                    urls: [],
                    clickCount: 0,
                    keypressCount: 0,
                    mouseActivityCount: 0,
                    activeMilliseconds: 0,
                    consoleLogCount: 3,
                    consoleWarnCount: 2,
                    consoleErrorCount: 1,
                    size: expect.any(Number),
                    messageCount: 0,
                    snapshotSource: null,
                    snapshotLibrary: null,
                }),
            ])
            expect(mockOffsetManager.commit).toHaveBeenCalledTimes(1)
        })

        it('should not commit offsets if metadata storage fails', async () => {
            const error = new Error('Metadata store failed')
            mockMetadataStore.storeSessionBlocks.mockRejectedValueOnce(error)

            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            await recorder.record(message)
            await expect(recorder.flush()).rejects.toThrow(error)

            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.flush).toHaveBeenCalledTimes(1)
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledTimes(1)
            expect(mockOffsetManager.commit).not.toHaveBeenCalled()
        })

        it('should not commit offsets if console log flush fails', async () => {
            const error = new Error('Console log flush failed')
            mockConsoleLogStore.flush.mockRejectedValueOnce(error)

            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            await recorder.record(message)
            await expect(recorder.flush()).rejects.toThrow(error)

            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockConsoleLogStore.flush).toHaveBeenCalledTimes(1)
            expect(mockMetadataStore.storeSessionBlocks).not.toHaveBeenCalled()
            expect(mockOffsetManager.commit).not.toHaveBeenCalled()
        })

        it('should store metadata for all sessions in batch', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: DateTime.fromISO('2025-01-01T10:00:00.000Z').toMillis(),
                        data: { source: 1 },
                    },
                ]),
                createMessage(
                    'session2',
                    [
                        {
                            type: EventType.FullSnapshot,
                            timestamp: DateTime.fromISO('2025-01-01T10:00:02.000Z').toMillis(),
                            data: { source: 2 },
                        },
                    ],
                    {},
                    2,
                    'other_distinct_id'
                ),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledWith(
                expect.arrayContaining([
                    expect.objectContaining({
                        sessionId: 'session1',
                        teamId: 1,
                        distinctId: 'distinct_id',
                        startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                        endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                        blockUrl: 's3://test/file?range=bytes=0-99',
                        blockLength: 100,
                        firstUrl: null,
                        urls: [],
                        clickCount: 0,
                        keypressCount: 0,
                        mouseActivityCount: 0,
                        activeMilliseconds: 0,
                        consoleLogCount: 3,
                        consoleWarnCount: 2,
                        consoleErrorCount: 1,
                        size: expect.any(Number),
                        messageCount: 0,
                        snapshotSource: null,
                        snapshotLibrary: null,
                    }),
                    expect.objectContaining({
                        sessionId: 'session2',
                        teamId: 2,
                        distinctId: 'other_distinct_id',
                        startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                        endDateTime: DateTime.fromISO('2025-01-01T10:00:02.000Z'),
                        blockUrl: 's3://test/file?range=bytes=0-99',
                        blockLength: 100,
                        firstUrl: null,
                        urls: [],
                        clickCount: 0,
                        keypressCount: 0,
                        mouseActivityCount: 0,
                        activeMilliseconds: 0,
                        consoleLogCount: 3,
                        consoleWarnCount: 2,
                        consoleErrorCount: 1,
                        size: expect.any(Number),
                        messageCount: 0,
                        snapshotSource: null,
                        snapshotLibrary: null,
                    }),
                ])
            )
        })
    })

    describe('partition handling', () => {
        it('should flush all partitions', async () => {
            const messages = [
                createMessage(
                    'session1',
                    [
                        {
                            type: EventType.FullSnapshot,
                            timestamp: 1000,
                            data: { source: 1 },
                        },
                    ],
                    { partition: 1 }
                ),
                createMessage(
                    'session2',
                    [
                        {
                            type: EventType.IncrementalSnapshot,
                            timestamp: 2000,
                            data: { source: 2 },
                        },
                    ],
                    { partition: 2 }
                ),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)
            const lines1 = parseLines(writtenData[0])
            const lines2 = parseLines(writtenData[1])
            expect(lines1).toEqual([['window1', messages[0].message.eventsByWindowId.window1[0]]])
            expect(lines2).toEqual([['window1', messages[1].message.eventsByWindowId.window1[0]]])
            expect(mockWriter.finish).toHaveBeenCalledTimes(1)
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledTimes(1)
            expect(mockOffsetManager.commit).toHaveBeenCalledTimes(1)
        })

        it('should not flush discarded partitions', async () => {
            const messages = [
                createMessage(
                    'session1',
                    [
                        {
                            type: EventType.FullSnapshot,
                            timestamp: 1000,
                            data: { source: 1 },
                        },
                    ],
                    { partition: 1 }
                ),
                createMessage(
                    'session2',
                    [
                        {
                            type: EventType.IncrementalSnapshot,
                            timestamp: 2000,
                            data: { source: 2 },
                        },
                    ],
                    { partition: 2 }
                ),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            recorder.discardPartition(1)
            await recorder.flush()

            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)
            const lines = parseLines(writtenData[0])
            // Should only contain message from partition 2
            expect(lines).toEqual([['window1', messages[1].message.eventsByWindowId.window1[0]]])
        })

        it('should correctly update size when discarding partitions', async () => {
            const message1 = createMessage(
                'session1',
                [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1 },
                    },
                ],
                { partition: 1 }
            )
            const message2 = createMessage(
                'session2',
                [
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2 },
                    },
                ],
                { partition: 2 }
            )

            const size1 = await recorder.record(message1)
            const size2 = await recorder.record(message2)
            expect(recorder.size).toBe(size1 + size2)

            recorder.discardPartition(1)
            expect(mockOffsetManager.discardPartition).toHaveBeenCalledWith(1)
            expect(recorder.size).toBe(size2)

            recorder.discardPartition(2)
            expect(mockOffsetManager.discardPartition).toHaveBeenCalledWith(2)
            expect(recorder.size).toBe(0)
        })

        it('should handle discarding non-existent partitions', async () => {
            const message = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            const bytesWritten = await recorder.record(message)
            expect(mockOffsetManager.trackOffset).toHaveBeenCalledWith({
                partition: message.message.metadata.partition,
                offset: message.message.metadata.offset,
            })
            expect(recorder.size).toBe(bytesWritten)

            recorder.discardPartition(999)
            expect(recorder.size).toBe(bytesWritten)
        })
    })

    describe('metrics', () => {
        it('should increment metrics on flush', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1 },
                    },
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2 },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Meta,
                        timestamp: 1500,
                        data: { href: 'https://example.com' },
                    },
                ]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenLastCalledWith(2) // Two sessions
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenLastCalledWith(3) // Three events total
        })

        it('should not increment metrics when no events are flushed', async () => {
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(0)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(0)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(0)
        })

        it('should not count events from discarded partitions', async () => {
            const messages = [
                createMessage(
                    'session1',
                    [
                        {
                            type: EventType.FullSnapshot,
                            timestamp: 1000,
                            data: { source: 1 },
                        },
                    ],
                    { partition: 1 }
                ),
                createMessage(
                    'session2',
                    [
                        {
                            type: EventType.IncrementalSnapshot,
                            timestamp: 2000,
                            data: { source: 2 },
                        },
                    ],
                    { partition: 2 }
                ),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            recorder.discardPartition(1)
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenLastCalledWith(1) // Only session from partition 2
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenLastCalledWith(1) // Only event from partition 2
        })

        it('should not count sessions again on subsequent flushes', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1 },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Meta,
                        timestamp: 1500,
                        data: { href: 'https://example.com' },
                    },
                ]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenLastCalledWith(2) // Two sessions
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenLastCalledWith(2) // Two events

            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(1)

            const message3 = createMessage('session3', [
                {
                    type: EventType.Custom,
                    timestamp: 2000,
                    data: { custom: 'data' },
                },
            ])
            await recorder.record(message3)
            await recorder.flush()

            expect(SessionBatchMetrics.incrementBatchesFlushed).toHaveBeenCalledTimes(2)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenCalledTimes(2)
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenCalledTimes(2)
            expect(SessionBatchMetrics.incrementSessionsFlushed).toHaveBeenLastCalledWith(1) // Only the new session
            expect(SessionBatchMetrics.incrementEventsFlushed).toHaveBeenLastCalledWith(1) // Only the new event
        })
    })

    describe('metadata handling', () => {
        it('should pass non-default metadata values to storeSessionBlocks', async () => {
            // Create a custom mock implementation of SnappySessionRecorderMock that returns non-default values
            const customRecorder = new SnappySessionRecorderMock('session_custom', 3, 'test_batch_id')

            // Override the end method to return non-default values
            customRecorder.end = jest.fn().mockReturnValue({
                buffer: Buffer.from('test'),
                eventCount: 5,
                startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                endDateTime: DateTime.fromISO('2025-01-01T10:00:10.000Z'),
                firstUrl: 'https://example.com/start',
                urls: ['https://example.com/start', 'https://example.com/page1', 'https://example.com/page2'],
                clickCount: 10,
                keypressCount: 25,
                mouseActivityCount: 50,
                activeMilliseconds: 8000,
                size: 1024,
                messageCount: 15,
                snapshotSource: 'web',
                snapshotLibrary: 'rrweb@1.0.0',
                batchId: 'test_batch_id',
            })

            jest.mocked(SnappySessionRecorder).mockImplementationOnce(
                () => customRecorder as unknown as SnappySessionRecorder
            )

            jest.mocked(SessionConsoleLogRecorder).mockImplementationOnce(
                (_sessionId, _teamId, _batchId) =>
                    ({
                        recordMessage: jest.fn().mockResolvedValue(undefined),
                        end: jest.fn().mockReturnValue({
                            consoleLogCount: 5,
                            consoleWarnCount: 3,
                            consoleErrorCount: 2,
                        }),
                    }) as unknown as SessionConsoleLogRecorder
            )

            const message = createMessage('session_custom', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
            ])

            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-01T10:00:00.000Z'),
                Number.MAX_SAFE_INTEGER
            )
            await recorder.record(message)
            await recorder.flush()

            // Verify that the metadata store received both the non-default values and console log counts
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledWith([
                expect.objectContaining({
                    sessionId: 'session_custom',
                    teamId: 3,
                    distinctId: 'distinct_id',
                    startDateTime: DateTime.fromISO('2025-01-01T10:00:00.000Z'),
                    endDateTime: DateTime.fromISO('2025-01-01T10:00:10.000Z'),
                    blockUrl: 's3://test/file?range=bytes=0-99',
                    blockLength: 100,
                    firstUrl: 'https://example.com/start',
                    urls: ['https://example.com/start', 'https://example.com/page1', 'https://example.com/page2'],
                    clickCount: 10,
                    keypressCount: 25,
                    mouseActivityCount: 50,
                    activeMilliseconds: 8000,
                    consoleLogCount: 5,
                    consoleWarnCount: 3,
                    consoleErrorCount: 2,
                    size: 1024,
                    messageCount: 15,
                    snapshotSource: 'web',
                    snapshotLibrary: 'rrweb@1.0.0',
                }),
            ])
        })

        it('should use the same batch ID for all sessions in a batch', async () => {
            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]),
                createMessage('session2', [{ type: EventType.Meta, timestamp: 2000, data: {} }]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            const storedBlocks = mockMetadataStore.storeSessionBlocks.mock.calls[0][0]
            expect(storedBlocks).toHaveLength(2)

            // All sessions should have the same batch ID
            const batchId = storedBlocks[0].batchId
            expect(batchId).toBeTruthy()
            expect(typeof batchId).toBe('string')
            expect(storedBlocks[1].batchId).toBe(batchId)
        })

        it('should generate UUIDv7 format batch IDs', async () => {
            await recorder.record(createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]))
            await recorder.flush()

            const batchId = mockMetadataStore.storeSessionBlocks.mock.calls[0][0][0].batchId
            expect(uuidValidate(batchId)).toBe(true)
        })

        it('should store event counts from session block recorders', async () => {
            const messages = [
                createMessage('session1', [
                    {
                        type: EventType.FullSnapshot,
                        timestamp: 1000,
                        data: { source: 1 },
                    },
                    {
                        type: EventType.IncrementalSnapshot,
                        timestamp: 2000,
                        data: { source: 2 },
                    },
                ]),
                createMessage('session2', [
                    {
                        type: EventType.Meta,
                        timestamp: 1500,
                        data: { href: 'https://example.com' },
                    },
                ]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }
            await recorder.flush()

            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledWith(
                expect.arrayContaining([
                    expect.objectContaining({
                        sessionId: 'session1',
                        eventCount: 2,
                    }),
                    expect.objectContaining({
                        sessionId: 'session2',
                        eventCount: 1,
                    }),
                ])
            )
        })

        it('should reset event counts after flush', async () => {
            const message1 = createMessage('session1', [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1 },
                },
                {
                    type: EventType.IncrementalSnapshot,
                    timestamp: 2000,
                    data: { source: 2 },
                },
            ])

            await recorder.record(message1)
            await recorder.flush()

            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenLastCalledWith([
                expect.objectContaining({
                    sessionId: 'session1',
                    eventCount: 2,
                }),
            ])

            const message2 = createMessage('session1', [
                {
                    type: EventType.Meta,
                    timestamp: 3000,
                    data: { href: 'https://example.com' },
                },
            ])

            await recorder.record(message2)
            await recorder.flush()

            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenLastCalledWith([
                expect.objectContaining({
                    sessionId: 'session1',
                    eventCount: 1,
                }),
            ])
        })
    })

    describe('error handling', () => {
        it('should handle errors from session streams', async () => {
            const events = [
                {
                    type: EventType.FullSnapshot,
                    timestamp: 1000,
                    data: { source: 1, adds: [{ parentId: 1, nextId: 2, node: { tag: 'div' } }] },
                },
            ]

            jest.mocked(SnappySessionRecorder).mockImplementation(
                () =>
                    ({
                        recordMessage: jest.fn().mockReturnValue(1),
                        end: () => Promise.reject(new Error('Stream read error')),
                    }) as unknown as SnappySessionRecorder
            )

            await recorder.record(createMessage('session', events))

            const flushPromise = recorder.flush()

            await expect(flushPromise).rejects.toThrow('Stream read error')

            expect(mockWriter.finish).not.toHaveBeenCalled()
            expect(mockMetadataStore.storeSessionBlocks).not.toHaveBeenCalled()
            expect(mockOffsetManager.commit).not.toHaveBeenCalled()
        })

        it('should handle writer errors', async () => {
            const error = new Error('Write failed')
            mockWriter.writeSession.mockRejectedValueOnce(error)

            const message = createMessage('session1', [{ type: 1, timestamp: 1, data: {} }])
            await recorder.record(message)

            await expect(recorder.flush()).rejects.toThrow(error)

            expect(mockWriter.finish).not.toHaveBeenCalled()
            expect(mockMetadataStore.storeSessionBlocks).not.toHaveBeenCalled()
            expect(mockOffsetManager.commit).not.toHaveBeenCalled()
        })
    })

    describe('rate limiting', () => {
        it('should allow events up to the limit', async () => {
            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                3
            )

            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 3000, data: {} }]),
            ]

            for (const message of messages) {
                const bytesWritten = await recorder.record(message)
                expect(bytesWritten).toBeGreaterThan(0)
            }

            await recorder.flush()
            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)
            expect(writtenData).toHaveLength(1)
        })

        it('should block events after limit is exceeded', async () => {
            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                2
            )

            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 3000, data: {} }]),
            ]

            const bytesWritten1 = await recorder.record(messages[0])
            const bytesWritten2 = await recorder.record(messages[1])
            const bytesWritten3 = await recorder.record(messages[2])

            expect(bytesWritten1).toBeGreaterThan(0)
            expect(bytesWritten2).toBeGreaterThan(0)
            expect(bytesWritten3).toBe(0)

            await recorder.flush()
            const writtenData = captureWrittenData(mockWriter.writeSession as jest.Mock)
            expect(writtenData).toHaveLength(0)
        })

        it('should delete session recorders when rate limited', async () => {
            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                1
            )

            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }]),
            ]

            await recorder.record(messages[0])
            await recorder.record(messages[1])

            await recorder.flush()
            expect(mockWriter.writeSession).not.toHaveBeenCalled()
        })

        it('should track offsets for rate limited events', async () => {
            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                1
            )

            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }], { offset: 100 }),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }], { offset: 101 }),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 3000, data: {} }], { offset: 102 }),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }

            expect(mockOffsetManager.trackOffset).toHaveBeenCalledWith({ partition: 1, offset: 100 })
            expect(mockOffsetManager.trackOffset).toHaveBeenCalledWith({ partition: 1, offset: 101 })
            expect(mockOffsetManager.trackOffset).toHaveBeenCalledWith({ partition: 1, offset: 102 })
        })

        it('should rate limit sessions independently', async () => {
            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                2
            )

            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]),
                createMessage('session2', [{ type: EventType.Meta, timestamp: 1100, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }]),
                createMessage('session2', [{ type: EventType.Meta, timestamp: 2100, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 3000, data: {} }]),
                createMessage('session2', [{ type: EventType.Meta, timestamp: 3100, data: {} }]),
            ]

            const results = []
            for (const message of messages) {
                results.push(await recorder.record(message))
            }

            expect(results[0]).toBeGreaterThan(0)
            expect(results[1]).toBeGreaterThan(0)
            expect(results[2]).toBeGreaterThan(0)
            expect(results[3]).toBeGreaterThan(0)
            expect(results[4]).toBe(0)
            expect(results[5]).toBe(0)

            await recorder.flush()
            expect(mockWriter.writeSession).not.toHaveBeenCalled()
        })

        it('should clear rate limiter state after flush', async () => {
            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                2
            )

            const messages1 = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }]),
            ]

            for (const message of messages1) {
                await recorder.record(message)
            }

            await recorder.flush()
            jest.clearAllMocks()
            mockStorage.newBatch.mockReturnValue(mockWriter)

            const messages2 = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 3000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 4000, data: {} }]),
            ]

            const bytesWritten1 = await recorder.record(messages2[0])
            const bytesWritten2 = await recorder.record(messages2[1])

            expect(bytesWritten1).toBeGreaterThan(0)
            expect(bytesWritten2).toBeGreaterThan(0)
        })

        it('should clean up rate limiter state when partition is discarded', async () => {
            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                1
            )

            const message1 = createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }], {
                partition: 1,
            })
            const message2 = createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }], {
                partition: 1,
            })

            await recorder.record(message1)
            await recorder.record(message2)

            recorder.discardPartition(1)

            const message3 = createMessage('session1', [{ type: EventType.Meta, timestamp: 3000, data: {} }], {
                partition: 2,
            })
            const bytesWritten = await recorder.record(message3)
            expect(bytesWritten).toBeGreaterThan(0)
        })

        it('should handle rate limiting with different team IDs', async () => {
            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                1
            )

            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }], {}, 1),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }], {}, 2),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 3000, data: {} }], {}, 1),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 4000, data: {} }], {}, 2),
            ]

            const results = []
            for (const message of messages) {
                results.push(await recorder.record(message))
            }

            expect(results[0]).toBeGreaterThan(0)
            expect(results[1]).toBeGreaterThan(0)
            expect(results[2]).toBe(0)
            expect(results[3]).toBe(0)
        })

        it('should increment rate limited metrics', async () => {
            const { SessionBatchMetrics } = require('./metrics')
            jest.clearAllMocks()

            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                2
            )

            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 3000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 4000, data: {} }]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }

            expect(SessionBatchMetrics.incrementSessionsRateLimited).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsRateLimited).toHaveBeenCalledTimes(2)
        })

        it('should only increment sessionsRateLimited once per session', async () => {
            const { SessionBatchMetrics } = require('./metrics')
            jest.clearAllMocks()

            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                1
            )

            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 3000, data: {} }]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }

            expect(SessionBatchMetrics.incrementSessionsRateLimited).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsRateLimited).toHaveBeenCalledTimes(2)
        })

        it('should increment metrics for each rate limited session', async () => {
            const { SessionBatchMetrics } = require('./metrics')
            jest.clearAllMocks()

            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                1
            )

            const messages = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]),
                createMessage('session2', [{ type: EventType.Meta, timestamp: 1100, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }]),
                createMessage('session2', [{ type: EventType.Meta, timestamp: 2100, data: {} }]),
            ]

            for (const message of messages) {
                await recorder.record(message)
            }

            expect(SessionBatchMetrics.incrementSessionsRateLimited).toHaveBeenCalledTimes(2)
            expect(SessionBatchMetrics.incrementEventsRateLimited).toHaveBeenCalledTimes(2)
        })

        it('should reset rate limited tracking after flush', async () => {
            const { SessionBatchMetrics } = require('./metrics')
            jest.clearAllMocks()

            recorder = new SessionBatchRecorder(
                mockOffsetManager,
                mockStorage,
                mockMetadataStore,
                mockConsoleLogStore,
                new Date('2025-01-02 00:00:00Z'),
                1
            )

            const messages1 = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 1000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 2000, data: {} }]),
            ]

            for (const message of messages1) {
                await recorder.record(message)
            }

            await recorder.flush()
            jest.clearAllMocks()
            mockStorage.newBatch.mockReturnValue(mockWriter)

            const messages2 = [
                createMessage('session1', [{ type: EventType.Meta, timestamp: 3000, data: {} }]),
                createMessage('session1', [{ type: EventType.Meta, timestamp: 4000, data: {} }]),
            ]

            for (const message of messages2) {
                await recorder.record(message)
            }

            expect(SessionBatchMetrics.incrementSessionsRateLimited).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementEventsRateLimited).toHaveBeenCalledTimes(1)
        })
    })
})

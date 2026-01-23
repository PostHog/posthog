/**
 * Integration tests for session recording encryption
 *
 * Tests the full round-trip of:
 * 1. Recording session events
 * 2. Encrypting block data with per-block nonces
 * 3. Storing encrypted data
 * 4. Decrypting block data
 * 5. Verifying original events are recovered
 */
import sodium from 'libsodium-wrappers'
import { DateTime } from 'luxon'
import snappy from 'snappy'

import { RecordingDecryptor } from '../../session-recording-api/decryptor'
import { RecordingEncryptor } from '../../session-recording-api/encryptor'
import { InMemoryKeyStore } from '../../session-recording-api/keystore'
import { SessionKeyDeletedError } from '../../session-recording-api/types'
import { parseJSON } from '../../utils/json-parse'
import { KafkaOffsetManager } from '../kafka/offset-manager'
import { MessageWithTeam } from '../teams/types'
import { SessionBatchFileStorage, SessionBatchFileWriter, WriteSessionData } from './session-batch-file-storage'
import { SessionBatchRecorder } from './session-batch-recorder'
import { SessionBlockMetadata } from './session-block-metadata'
import { SessionConsoleLogStore } from './session-console-log-store'
import { SessionFilter } from './session-filter'
import { SessionMetadataStore } from './session-metadata-store'
import { SessionTracker } from './session-tracker'

const enum EventType {
    FullSnapshot = 2,
    IncrementalSnapshot = 3,
    Meta = 4,
}

describe('session recording encryption integration', () => {
    let recorder: SessionBatchRecorder
    let keyStore: InMemoryKeyStore
    let encryptor: RecordingEncryptor
    let decryptor: RecordingDecryptor
    let mockOffsetManager: jest.Mocked<KafkaOffsetManager>
    let mockStorage: jest.Mocked<SessionBatchFileStorage>
    let mockWriter: jest.Mocked<SessionBatchFileWriter>
    let mockMetadataStore: jest.Mocked<SessionMetadataStore>
    let mockConsoleLogStore: jest.Mocked<SessionConsoleLogStore>
    let mockSessionTracker: jest.Mocked<SessionTracker>
    let mockSessionFilter: jest.Mocked<SessionFilter>
    let batchBuffer: Uint8Array
    let currentOffset: number

    beforeAll(async () => {
        await sodium.ready
    })

    beforeEach(async () => {
        currentOffset = 0
        batchBuffer = new Uint8Array()

        keyStore = new InMemoryKeyStore()
        await keyStore.start()

        encryptor = new RecordingEncryptor(keyStore)
        await encryptor.start()

        decryptor = new RecordingDecryptor(keyStore)
        await decryptor.start()

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
                    retentionPeriodDays: null,
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

        mockSessionTracker = {
            trackSession: jest.fn().mockResolvedValue(true), // Return true to trigger key generation
        } as unknown as jest.Mocked<SessionTracker>

        mockSessionFilter = {
            isBlocked: jest.fn().mockResolvedValue(false),
            handleNewSession: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionFilter>

        recorder = new SessionBatchRecorder(
            mockOffsetManager,
            mockStorage,
            mockMetadataStore,
            mockConsoleLogStore,
            mockSessionTracker,
            mockSessionFilter,
            keyStore,
            encryptor
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
            token: null,
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

    const readEncryptedBlockFromBatch = (blockMetadata: SessionBlockMetadata): Buffer => {
        const match = blockMetadata.blockUrl?.match(/bytes=(\d+)-(\d+)/)
        if (!match) {
            throw new Error('Invalid block URL format')
        }
        const startOffset = parseInt(match[1])
        const endOffset = parseInt(match[2])
        return Buffer.from(batchBuffer.subarray(startOffset, endOffset + 1))
    }

    it('should encrypt block data during recording and decrypt correctly', async () => {
        const sessionId = 'encrypted-session-1'
        const teamId = 42
        const originalEvents = [
            { type: EventType.FullSnapshot, data: { source: 1, snapshot: { html: '<div>Hello World</div>' } } },
            { type: EventType.IncrementalSnapshot, data: { source: 2, mutations: [{ id: 1, text: 'updated' }] } },
            { type: EventType.Meta, data: { href: 'https://example.com', width: 1920, height: 1080 } },
        ]

        const message = createMessage(sessionId, teamId, originalEvents)
        await recorder.record(message)
        const metadata = await recorder.flush()

        expect(metadata).toHaveLength(1)
        const blockMetadata = metadata[0]
        expect(blockMetadata.sessionId).toBe(sessionId)
        expect(blockMetadata.teamId).toBe(teamId)

        // Read the encrypted block from the batch
        const encryptedBlock = readEncryptedBlockFromBatch(blockMetadata)

        // Verify the block is encrypted (should not be valid snappy data)
        await expect(snappy.uncompress(encryptedBlock)).rejects.toThrow()

        // Decrypt the block
        const decryptedBlock = await decryptor.decryptBlock(sessionId, teamId, encryptedBlock)

        // Decompress and parse
        const decompressed = await snappy.uncompress(decryptedBlock)
        const events: [string, any][] = decompressed
            .toString()
            .trim()
            .split('\n')
            .map((line) => parseJSON(line))

        // Verify original events are recovered
        expect(events).toHaveLength(originalEvents.length)
        events.forEach(([windowId, event], index) => {
            expect(windowId).toBe('window1')
            expect(event.type).toBe(originalEvents[index].type)
            expect(event.data).toEqual(originalEvents[index].data)
        })
    })

    it('should use different nonces for different blocks of the same session', async () => {
        const sessionId = 'multi-block-session'
        const teamId = 42

        // Record first message
        mockSessionTracker.trackSession.mockResolvedValueOnce(true) // New session
        const message1 = createMessage(sessionId, teamId, [
            { type: EventType.FullSnapshot, data: { source: 1, snapshot: { html: '<div>Block 1</div>' } } },
        ])
        await recorder.record(message1)
        const metadata1 = await recorder.flush()

        const encryptedBlock1 = readEncryptedBlockFromBatch(metadata1[0])
        const nonce1 = encryptedBlock1.subarray(0, sodium.crypto_secretbox_NONCEBYTES)

        // Reset batch buffer for second recording
        batchBuffer = new Uint8Array()
        currentOffset = 0

        // Create new recorder for second batch
        recorder = new SessionBatchRecorder(
            mockOffsetManager,
            mockStorage,
            mockMetadataStore,
            mockConsoleLogStore,
            mockSessionTracker,
            mockSessionFilter,
            keyStore,
            encryptor
        )

        // Record second message (same session, different batch)
        mockSessionTracker.trackSession.mockResolvedValueOnce(false) // Existing session
        const message2 = createMessage(sessionId, teamId, [
            { type: EventType.IncrementalSnapshot, data: { source: 2, mutations: [{ id: 2 }] } },
        ])
        await recorder.record(message2)
        const metadata2 = await recorder.flush()

        const encryptedBlock2 = readEncryptedBlockFromBatch(metadata2[0])
        const nonce2 = encryptedBlock2.subarray(0, sodium.crypto_secretbox_NONCEBYTES)

        // Verify nonces are different
        expect(Buffer.compare(nonce1, nonce2)).not.toBe(0)

        // Verify both blocks can be decrypted correctly
        const decrypted1 = await decryptor.decryptBlock(sessionId, teamId, encryptedBlock1)
        const decrypted2 = await decryptor.decryptBlock(sessionId, teamId, encryptedBlock2)

        const events1 = (await snappy.uncompress(decrypted1)).toString().trim().split('\n').map(parseJSON)
        const events2 = (await snappy.uncompress(decrypted2)).toString().trim().split('\n').map(parseJSON)

        expect(events1[0][1].data.snapshot.html).toBe('<div>Block 1</div>')
        expect(events2[0][1].data.mutations[0].id).toBe(2)
    })

    it('should throw SessionKeyDeletedError when trying to decrypt deleted session', async () => {
        const sessionId = 'to-be-deleted-session'
        const teamId = 42

        const message = createMessage(sessionId, teamId, [
            { type: EventType.FullSnapshot, data: { source: 1, snapshot: { html: '<div>Secret</div>' } } },
        ])
        await recorder.record(message)
        const metadata = await recorder.flush()

        const encryptedBlock = readEncryptedBlockFromBatch(metadata[0])

        // Verify decryption works before deletion
        const decryptedBefore = await decryptor.decryptBlock(sessionId, teamId, encryptedBlock)
        expect(decryptedBefore).toBeDefined()

        // Delete the session key
        const deleted = await keyStore.deleteKey(sessionId, teamId)
        expect(deleted).toBe(true)

        // Verify decryption fails after deletion
        await expect(decryptor.decryptBlock(sessionId, teamId, encryptedBlock)).rejects.toThrow(SessionKeyDeletedError)
    })

    it('should encrypt multiple sessions with different keys', async () => {
        const sessions = [
            { sessionId: 'session-a', teamId: 1 },
            { sessionId: 'session-b', teamId: 1 },
            { sessionId: 'session-c', teamId: 2 },
        ]

        // Record all sessions
        for (const { sessionId, teamId } of sessions) {
            const message = createMessage(sessionId, teamId, [
                { type: EventType.FullSnapshot, data: { source: 1, snapshot: { html: `<div>${sessionId}</div>` } } },
            ])
            await recorder.record(message)
        }

        const metadata = await recorder.flush()
        expect(metadata).toHaveLength(3)

        // Verify each session can be decrypted independently
        for (const block of metadata) {
            const encryptedBlock = readEncryptedBlockFromBatch(block)
            const decryptedBlock = await decryptor.decryptBlock(block.sessionId, block.teamId, encryptedBlock)
            const events = (await snappy.uncompress(decryptedBlock)).toString().trim().split('\n').map(parseJSON)

            expect(events[0][1].data.snapshot.html).toBe(`<div>${block.sessionId}</div>`)
        }

        // Verify cross-session decryption fails (wrong key)
        const block0 = metadata[0]
        const block1 = metadata[1]
        const encryptedBlock0 = readEncryptedBlockFromBatch(block0)

        // Try to decrypt block0 with block1's session key - should fail
        await expect(async () => {
            const wrongKey = await keyStore.getKey(block1.sessionId, block1.teamId)
            decryptor.decryptBlockWithKey(block0.sessionId, block0.teamId, encryptedBlock0, wrongKey)
        }).rejects.toThrow()
    })
})

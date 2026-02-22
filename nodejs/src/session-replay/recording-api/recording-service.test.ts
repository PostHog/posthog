import { NoSuchKey, S3Client } from '@aws-sdk/client-s3'

import { PostgresRouter } from '../../utils/db/postgres'
import { SessionMetadataStore } from '../shared/metadata/session-metadata-store'
import { RecordingService } from './recording-service'
import { KeyStore, RecordingDecryptor, SessionKeyDeletedError } from './types'

describe('RecordingService', () => {
    let service: RecordingService
    let mockS3Send: jest.Mock
    let mockS3Client: S3Client
    let mockKeyStore: jest.Mocked<KeyStore>
    let mockDecryptor: jest.Mocked<RecordingDecryptor>
    let mockMetadataStore: jest.Mocked<SessionMetadataStore>
    let mockPostgres: jest.Mocked<PostgresRouter>

    beforeEach(() => {
        mockS3Send = jest.fn()
        mockS3Client = {
            send: mockS3Send,
        } as unknown as S3Client

        mockKeyStore = {
            start: jest.fn(),
            generateKey: jest.fn(),
            getKey: jest.fn(),
            deleteKey: jest.fn(),
            stop: jest.fn(),
        } as unknown as jest.Mocked<KeyStore>

        mockDecryptor = {
            start: jest.fn(),
            decryptBlock: jest.fn(),
            decryptBlockWithKey: jest.fn(),
        } as unknown as jest.Mocked<RecordingDecryptor>

        mockMetadataStore = {
            storeSessionBlocks: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionMetadataStore>

        mockPostgres = {
            query: jest.fn().mockResolvedValue({ rows: [] }),
        } as unknown as jest.Mocked<PostgresRouter>

        service = new RecordingService(
            mockS3Client,
            'test-bucket',
            'session_recordings',
            mockKeyStore,
            mockDecryptor,
            mockMetadataStore,
            mockPostgres
        )
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('validateS3Key', () => {
        it.each([
            ['session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee', true],
            ['session_recordings/90d/1764634738680-abcdef0123456789', true],
            ['session_recordings/1y/1764634738680-0000000000000000', true],
            ['session_recordings/5y/1764634738680-ffffffffffffffff', true],
            ['../etc/passwd', false],
            ['other_prefix/30d/123-abcdef0123456789', false],
            ['session_recordings/7d/123-abcdef0123456789', false],
            ['session_recordings/30d/file', false],
            ['session_recordings/30d/123', false],
            ['session_recordings/30d/123-abc', false],
            ['session_recordings/30d/123-abcdef012345678z', false],
            ['session_recordings/30d/-abcdef0123456789', false],
        ])('validates key "%s" as %s', (key, expected) => {
            expect(service.validateS3Key(key)).toBe(expected)
        })
    })

    describe('formatS3KeyError', () => {
        it('returns formatted error message', () => {
            const error = service.formatS3KeyError()

            expect(error).toContain('session_recordings')
            expect(error).toContain('30d')
            expect(error).toContain('90d')
            expect(error).toContain('1y')
            expect(error).toContain('5y')
        })
    })

    describe('getBlock', () => {
        const validParams = {
            sessionId: 'session-123',
            teamId: 1,
            key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee',
            startByte: 0,
            endByte: 100,
        }

        it('returns decrypted data on success', async () => {
            const mockBody = {
                transformToByteArray: jest.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
            }
            mockS3Send.mockResolvedValue({ Body: mockBody })
            mockDecryptor.decryptBlock.mockResolvedValue(Buffer.from('decrypted data'))

            const result = await service.getBlock(validParams)

            expect(result).toEqual({ ok: true, data: Buffer.from('decrypted data') })
            expect(mockDecryptor.decryptBlock).toHaveBeenCalledWith('session-123', 1, expect.any(Buffer))
        })

        it('returns not_found when S3 returns no body', async () => {
            mockS3Send.mockResolvedValue({ Body: null })

            const result = await service.getBlock(validParams)

            expect(result).toEqual({ ok: false, error: 'not_found' })
        })

        it('returns deleted with timestamp when session key was deleted', async () => {
            const mockBody = {
                transformToByteArray: jest.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
            }
            mockS3Send.mockResolvedValue({ Body: mockBody })
            mockDecryptor.decryptBlock.mockRejectedValue(new SessionKeyDeletedError('session-123', 1, 1700000000))

            const result = await service.getBlock(validParams)

            expect(result).toEqual({ ok: false, error: 'deleted', deletedAt: 1700000000 })
        })

        it('returns deleted with undefined timestamp when not available', async () => {
            const mockBody = {
                transformToByteArray: jest.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
            }
            mockS3Send.mockResolvedValue({ Body: mockBody })
            mockDecryptor.decryptBlock.mockRejectedValue(new SessionKeyDeletedError('session-123', 1, undefined))

            const result = await service.getBlock(validParams)

            expect(result).toEqual({ ok: false, error: 'deleted', deletedAt: undefined })
        })

        it('returns not_found when S3 throws NoSuchKey', async () => {
            mockS3Send.mockRejectedValue(new NoSuchKey({ message: 'The specified key does not exist.', $metadata: {} }))

            const result = await service.getBlock(validParams)

            expect(result).toEqual({ ok: false, error: 'not_found' })
        })

        it('propagates unexpected S3 errors', async () => {
            mockS3Send.mockRejectedValue(new Error('S3 network error'))

            await expect(service.getBlock(validParams)).rejects.toThrow('S3 network error')
        })

        it('propagates unexpected decryption errors', async () => {
            const mockBody = {
                transformToByteArray: jest.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
            }
            mockS3Send.mockResolvedValue({ Body: mockBody })
            mockDecryptor.decryptBlock.mockRejectedValue(new Error('crypto: bad nonce'))

            await expect(service.getBlock(validParams)).rejects.toThrow('crypto: bad nonce')
        })

        it('calls S3 with correct parameters', async () => {
            const mockBody = {
                transformToByteArray: jest.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
            }
            mockS3Send.mockResolvedValue({ Body: mockBody })
            mockDecryptor.decryptBlock.mockResolvedValue(Buffer.from('data'))

            await service.getBlock(validParams)

            expect(mockS3Send).toHaveBeenCalledWith(
                expect.objectContaining({
                    input: {
                        Bucket: 'test-bucket',
                        Key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee',
                        Range: 'bytes=0-100',
                    },
                })
            )
        })
    })

    describe('deleteSingleRecording', () => {
        it('returns deleted when key is newly deleted', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true, deletedAt: 1700000000 })

            const result = await service.deleteSingleRecording('session-123', 1)

            expect(result).toEqual({ sessionId: 'session-123', ok: true, status: 'deleted', deletedAt: 1700000000 })
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledWith([
                expect.objectContaining({ sessionId: 'session-123', teamId: 1, isDeleted: true }),
            ])
            expect(mockPostgres.query).toHaveBeenCalledTimes(3)
        })

        it('returns already_deleted without cleanup when key was already deleted', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                deleted: false,
                reason: 'already_deleted',
                deletedAt: 1700000000,
            })

            const result = await service.deleteSingleRecording('session-123', 1)

            expect(result).toEqual({
                sessionId: 'session-123',
                ok: true,
                status: 'already_deleted',
                deletedAt: 1700000000,
            })
            expect(mockMetadataStore.storeSessionBlocks).not.toHaveBeenCalled()
            expect(mockPostgres.query).not.toHaveBeenCalled()
        })

        it('returns shred_failed when key shred throws', async () => {
            mockKeyStore.deleteKey.mockRejectedValue(new Error('DynamoDB error'))

            const result = await service.deleteSingleRecording('session-123', 1)

            expect(result).toEqual({ sessionId: 'session-123', ok: false, error: 'shred_failed' })
        })

        it('returns cleanup_failed when kafka fails (postgres still attempted)', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true, deletedAt: 1700000000 })
            mockMetadataStore.storeSessionBlocks.mockRejectedValue(new Error('Kafka down'))

            const result = await service.deleteSingleRecording('session-123', 1)

            expect(result).toEqual({
                sessionId: 'session-123',
                ok: false,
                error: 'cleanup_failed',
                deletedAt: 1700000000,
            })
            expect(mockPostgres.query).toHaveBeenCalled()
        })

        it('returns cleanup_failed when postgres fails (kafka still attempted)', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true, deletedAt: 1700000000 })
            mockPostgres.query.mockRejectedValue(new Error('Postgres down'))

            const result = await service.deleteSingleRecording('session-123', 1)

            expect(result).toEqual({
                sessionId: 'session-123',
                ok: false,
                error: 'cleanup_failed',
                deletedAt: 1700000000,
            })
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalled()
        })

        it('returns cleanup_failed when both kafka and postgres fail', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true, deletedAt: 1700000000 })
            mockMetadataStore.storeSessionBlocks.mockRejectedValue(new Error('Kafka down'))
            mockPostgres.query.mockRejectedValue(new Error('Postgres down'))

            const result = await service.deleteSingleRecording('session-123', 1)

            expect(result).toEqual({
                sessionId: 'session-123',
                ok: false,
                error: 'cleanup_failed',
                deletedAt: 1700000000,
            })
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalled()
            expect(mockPostgres.query).toHaveBeenCalled()
        })

        it('works without metadata store configured', async () => {
            const serviceWithoutMetadata = new RecordingService(
                mockS3Client,
                'test-bucket',
                'session_recordings',
                mockKeyStore,
                mockDecryptor
            )
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true, deletedAt: 1700000000 })

            const result = await serviceWithoutMetadata.deleteSingleRecording('session-123', 1)

            expect(result).toEqual({ sessionId: 'session-123', ok: true, status: 'deleted', deletedAt: 1700000000 })
        })
    })

    describe('bulkDeleteRecordings', () => {
        it('returns empty array when no session IDs provided', async () => {
            const result = await service.bulkDeleteRecordings([], 1)

            expect(result).toEqual([])
            expect(mockKeyStore.deleteKey).not.toHaveBeenCalled()
            expect(mockPostgres.query).not.toHaveBeenCalled()
        })

        it('returns ok for all when all succeed', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true, deletedAt: 1700000000 })

            const result = await service.bulkDeleteRecordings(['session-1', 'session-2'], 1)

            expect(result).toEqual([
                { sessionId: 'session-1', ok: true, status: 'deleted', deletedAt: 1700000000 },
                { sessionId: 'session-2', ok: true, status: 'deleted', deletedAt: 1700000000 },
            ])
        })

        it('emits kafka events for newly deleted sessions only', async () => {
            mockKeyStore.deleteKey
                .mockResolvedValueOnce({ deleted: true, deletedAt: 1700000000 })
                .mockResolvedValueOnce({ deleted: false, reason: 'already_deleted', deletedAt: 1700000000 })

            await service.bulkDeleteRecordings(['new', 'already-deleted'], 1)

            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledTimes(1)
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledWith([
                expect.objectContaining({ sessionId: 'new', teamId: 1, isDeleted: true }),
            ])
        })

        it('batches postgres deletes for all shredded sessions', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true, deletedAt: 1700000000 })

            await service.bulkDeleteRecordings(['session-1', 'session-2'], 1)

            expect(mockPostgres.query).toHaveBeenCalledTimes(3)
            expect(mockPostgres.query).toHaveBeenCalledWith(
                expect.anything(),
                expect.stringContaining('ee_single_session_summary'),
                [1, ['session-1', 'session-2']],
                'bulkDeleteSessionSummaries'
            )
        })

        it('excludes already_deleted sessions from postgres batch', async () => {
            mockKeyStore.deleteKey
                .mockResolvedValueOnce({ deleted: true, deletedAt: 1700000000 })
                .mockResolvedValueOnce({ deleted: false, reason: 'already_deleted', deletedAt: 1700000000 })

            await service.bulkDeleteRecordings(['new-session', 'already-deleted-session'], 1)

            expect(mockPostgres.query).toHaveBeenCalledTimes(3)
            expect(mockPostgres.query).toHaveBeenCalledWith(
                expect.anything(),
                expect.stringContaining('ee_single_session_summary'),
                [1, ['new-session']],
                'bulkDeleteSessionSummaries'
            )
        })

        it('returns shred_failed for sessions where key shred throws', async () => {
            mockKeyStore.deleteKey
                .mockResolvedValueOnce({ deleted: true, deletedAt: 1700000000 })
                .mockRejectedValueOnce(new Error('DynamoDB error'))

            const result = await service.bulkDeleteRecordings(['session-1', 'session-2'], 1)

            expect(result).toEqual([
                { sessionId: 'session-1', ok: true, status: 'deleted', deletedAt: 1700000000 },
                { sessionId: 'session-2', ok: false, error: 'shred_failed' },
            ])
        })

        it('returns cleanup_failed when kafka emission fails', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true, deletedAt: 1700000000 })
            mockMetadataStore.storeSessionBlocks.mockRejectedValue(new Error('Kafka down'))

            const result = await service.bulkDeleteRecordings(['session-1'], 1)

            expect(result).toEqual([
                { sessionId: 'session-1', ok: false, error: 'cleanup_failed', deletedAt: 1700000000 },
            ])
        })

        it('skips postgres when all shreds fail', async () => {
            mockKeyStore.deleteKey.mockRejectedValue(new Error('DynamoDB error'))

            await service.bulkDeleteRecordings(['session-1'], 1)

            expect(mockPostgres.query).not.toHaveBeenCalled()
        })

        it('returns cleanup_failed when postgres batch fails', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true, deletedAt: 1700000000 })
            mockPostgres.query.mockRejectedValue(new Error('Postgres down'))

            const result = await service.bulkDeleteRecordings(['session-1'], 1)

            expect(result).toEqual([
                { sessionId: 'session-1', ok: false, error: 'cleanup_failed', deletedAt: 1700000000 },
            ])
        })

        it('kafka and postgres failures are independent', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true, deletedAt: 1700000000 })
            mockMetadataStore.storeSessionBlocks.mockRejectedValue(new Error('Kafka down'))
            mockPostgres.query.mockRejectedValue(new Error('Postgres down'))

            const result = await service.bulkDeleteRecordings(['session-1'], 1)

            expect(result).toEqual([
                { sessionId: 'session-1', ok: false, error: 'cleanup_failed', deletedAt: 1700000000 },
            ])
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalled()
            expect(mockPostgres.query).toHaveBeenCalled()
        })
    })
})

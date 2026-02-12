import { S3Client } from '@aws-sdk/client-s3'

import { PostgresRouter } from '../../utils/db/postgres'
import { SessionMetadataStore } from '../metadata/session-metadata-store'
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

    describe('deleteRecording', () => {
        it('returns ok, emits deletion event, and deletes postgres records when key is deleted', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true })

            const result = await service.deleteRecording('session-123', 1)

            expect(result).toEqual({ ok: true })
            expect(mockKeyStore.deleteKey).toHaveBeenCalledWith('session-123', 1)
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledWith([
                expect.objectContaining({
                    sessionId: 'session-123',
                    teamId: 1,
                    isDeleted: true,
                }),
            ])
            expect(mockPostgres.query).toHaveBeenCalledTimes(4)
            expect(mockPostgres.query).toHaveBeenCalledWith(
                expect.anything(),
                expect.stringContaining('ee_single_session_summary'),
                [1, 'session-123'],
                'deleteSessionSummary'
            )
            expect(mockPostgres.query).toHaveBeenCalledWith(
                expect.anything(),
                expect.stringContaining('posthog_sessionrecording'),
                [1, 'session-123'],
                'deleteSessionRecording'
            )
        })

        it('does not emit deletion event or delete postgres records when key is not found', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: false, reason: 'not_found' })

            const result = await service.deleteRecording('session-123', 1)

            expect(result).toEqual({ ok: false, error: 'not_found' })
            expect(mockMetadataStore.storeSessionBlocks).not.toHaveBeenCalled()
            expect(mockPostgres.query).not.toHaveBeenCalled()
        })

        it('does not emit deletion event or delete postgres records when key was already deleted', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                deleted: false,
                reason: 'already_deleted',
                deletedAt: 1700000000,
            })

            const result = await service.deleteRecording('session-123', 1)

            expect(result).toEqual({ ok: false, error: 'already_deleted', deletedAt: 1700000000 })
            expect(mockMetadataStore.storeSessionBlocks).not.toHaveBeenCalled()
            expect(mockPostgres.query).not.toHaveBeenCalled()
        })

        it('returns already_deleted with undefined timestamp when not available', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                deleted: false,
                reason: 'already_deleted',
                deletedAt: undefined,
            })

            const result = await service.deleteRecording('session-123', 1)

            expect(result).toEqual({ ok: false, error: 'already_deleted', deletedAt: undefined })
        })

        it('returns not_supported when keystore does not support deletion', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: false, reason: 'not_supported' })

            const result = await service.deleteRecording('session-123', 1)

            expect(result).toEqual({ ok: false, error: 'not_supported' })
        })

        it('still returns ok when metadata store fails after key deletion', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true })
            mockMetadataStore.storeSessionBlocks.mockRejectedValue(new Error('Kafka connection lost'))

            const result = await service.deleteRecording('session-123', 1)

            expect(result).toEqual({ ok: true })
            // Promise.allSettled runs both independently, so postgres is still called
            expect(mockPostgres.query).toHaveBeenCalled()
        })

        it('still returns ok when postgres fails after key deletion', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true })
            mockPostgres.query.mockRejectedValue(new Error('Postgres connection lost'))

            const result = await service.deleteRecording('session-123', 1)

            expect(result).toEqual({ ok: true })
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalled()
        })

        it('propagates unexpected errors', async () => {
            mockKeyStore.deleteKey.mockRejectedValue(new Error('Database error'))

            await expect(service.deleteRecording('session-123', 1)).rejects.toThrow('Database error')
        })

        it('works without metadata store configured', async () => {
            const serviceWithoutMetadata = new RecordingService(
                mockS3Client,
                'test-bucket',
                'session_recordings',
                mockKeyStore,
                mockDecryptor
            )
            mockKeyStore.deleteKey.mockResolvedValue({ deleted: true })

            const result = await serviceWithoutMetadata.deleteRecording('session-123', 1)

            expect(result).toEqual({ ok: true })
        })
    })
})

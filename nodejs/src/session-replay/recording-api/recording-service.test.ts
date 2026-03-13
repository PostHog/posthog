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
            mockDecryptor.decryptBlock.mockResolvedValue({
                data: Buffer.from('decrypted data'),
                sessionState: 'ciphertext',
            })

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

            expect(result).toEqual({ ok: false, error: 'deleted', deletedAt: 1700000000, deletedBy: '' })
        })

        it('returns deleted with undefined timestamp when not available', async () => {
            const mockBody = {
                transformToByteArray: jest.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
            }
            mockS3Send.mockResolvedValue({ Body: mockBody })
            mockDecryptor.decryptBlock.mockRejectedValue(new SessionKeyDeletedError('session-123', 1, undefined))

            const result = await service.getBlock(validParams)

            expect(result).toEqual({ ok: false, error: 'deleted', deletedAt: undefined, deletedBy: '' })
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
            mockDecryptor.decryptBlock.mockResolvedValue({ data: Buffer.from('data'), sessionState: 'ciphertext' })

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

    describe('deleteRecordings', () => {
        it('returns empty array when no session IDs provided', async () => {
            const result = await service.deleteRecordings([], 1, 'test@example.com')

            expect(result).toEqual([])
            expect(mockKeyStore.deleteKey).not.toHaveBeenCalled()
            expect(mockPostgres.query).not.toHaveBeenCalled()
        })

        it('returns ok for all when all succeed', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                status: 'deleted',
                deletedAt: 1700000000,
                deletedBy: 'test@example.com',
            })

            const result = await service.deleteRecordings(['session-1', 'session-2'], 1, 'test@example.com')

            expect(result).toEqual([
                {
                    sessionId: 'session-1',
                    ok: true,
                    status: 'deleted',
                    deletedAt: 1700000000,
                    deletedBy: 'test@example.com',
                },
                {
                    sessionId: 'session-2',
                    ok: true,
                    status: 'deleted',
                    deletedAt: 1700000000,
                    deletedBy: 'test@example.com',
                },
            ])
        })

        it('emits kafka events for newly deleted sessions only', async () => {
            mockKeyStore.deleteKey
                .mockResolvedValueOnce({ status: 'deleted', deletedAt: 1700000000, deletedBy: 'test@example.com' })
                .mockResolvedValueOnce({
                    status: 'already_deleted',
                    deletedAt: 1700000000,
                    deletedBy: 'original@example.com',
                })

            await service.deleteRecordings(['new', 'already-deleted'], 1, 'test@example.com')

            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledTimes(1)
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalledWith([
                expect.objectContaining({ sessionId: 'new', teamId: 1, isDeleted: true }),
            ])
        })

        it('batches postgres deletes for all shredded sessions', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                status: 'deleted',
                deletedAt: 1700000000,
                deletedBy: 'test@example.com',
            })

            await service.deleteRecordings(['session-1', 'session-2'], 1, 'test@example.com')

            // 3 DELETE statements + 1 activity log INSERT
            expect(mockPostgres.query).toHaveBeenCalledTimes(4)
            expect(mockPostgres.query).toHaveBeenCalledWith(
                expect.anything(),
                expect.stringContaining('ee_single_session_summary'),
                [1, ['session-1', 'session-2']],
                'deleteSessionSummaries'
            )
        })

        it('excludes already_deleted sessions from postgres batch', async () => {
            mockKeyStore.deleteKey
                .mockResolvedValueOnce({ status: 'deleted', deletedAt: 1700000000, deletedBy: 'test@example.com' })
                .mockResolvedValueOnce({
                    status: 'already_deleted',
                    deletedAt: 1700000000,
                    deletedBy: 'original@example.com',
                })

            await service.deleteRecordings(['new-session', 'already-deleted-session'], 1, 'test@example.com')

            // 3 DELETE statements + 1 activity log INSERT
            expect(mockPostgres.query).toHaveBeenCalledTimes(4)
            expect(mockPostgres.query).toHaveBeenCalledWith(
                expect.anything(),
                expect.stringContaining('ee_single_session_summary'),
                [1, ['new-session']],
                'deleteSessionSummaries'
            )
        })

        it('returns delete_failed for sessions where key shred throws', async () => {
            mockKeyStore.deleteKey
                .mockResolvedValueOnce({ status: 'deleted', deletedAt: 1700000000, deletedBy: 'test@example.com' })
                .mockRejectedValueOnce(new Error('DynamoDB error'))

            const result = await service.deleteRecordings(['session-1', 'session-2'], 1, 'test@example.com')

            expect(result).toEqual([
                {
                    sessionId: 'session-1',
                    ok: true,
                    status: 'deleted',
                    deletedAt: 1700000000,
                    deletedBy: 'test@example.com',
                },
                { sessionId: 'session-2', ok: false, status: 'delete_failed' },
            ])
        })

        it('reports success when kafka emission fails after shred', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                status: 'deleted',
                deletedAt: 1700000000,
                deletedBy: 'test@example.com',
            })
            mockMetadataStore.storeSessionBlocks.mockRejectedValue(new Error('Kafka down'))

            const result = await service.deleteRecordings(['session-1'], 1, 'test@example.com')

            expect(result).toEqual([
                {
                    sessionId: 'session-1',
                    ok: true,
                    status: 'deleted',
                    deletedAt: 1700000000,
                    deletedBy: 'test@example.com',
                },
            ])
        })

        it('inserts activity log entries for newly deleted sessions', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                status: 'deleted',
                deletedAt: 1700000000,
                deletedBy: 'test@example.com',
            })

            await service.deleteRecordings(['session-1', 'session-2'], 1, 'test@example.com')

            expect(mockPostgres.query).toHaveBeenCalledWith(
                expect.anything(),
                expect.stringContaining('posthog_activitylog'),
                [1, ['session-1', 'session-2'], expect.stringContaining('recording_shredded')],
                'logRecordingDeletion'
            )
        })

        it('does not insert activity log when all sessions were already deleted', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                status: 'already_deleted',
                deletedAt: 1700000000,
                deletedBy: 'original@example.com',
            })

            await service.deleteRecordings(['session-1'], 1, 'test@example.com')

            expect(mockPostgres.query).not.toHaveBeenCalled()
        })

        it('reports success when logActivity fails after shred', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                status: 'deleted',
                deletedAt: 1700000000,
                deletedBy: 'test@example.com',
            })
            let callCount = 0
            mockPostgres.query.mockImplementation((() => {
                if (++callCount === 4) {
                    return Promise.reject(new Error('Activity log insert failed'))
                }
                return Promise.resolve({ rows: [] })
            }) as any)

            const result = await service.deleteRecordings(['session-1'], 1, 'test@example.com')

            expect(result).toEqual([
                {
                    sessionId: 'session-1',
                    ok: true,
                    status: 'deleted',
                    deletedAt: 1700000000,
                    deletedBy: 'test@example.com',
                },
            ])
        })

        it('skips postgres when all shreds fail', async () => {
            mockKeyStore.deleteKey.mockRejectedValue(new Error('DynamoDB error'))

            await service.deleteRecordings(['session-1'], 1, 'test@example.com')

            expect(mockPostgres.query).not.toHaveBeenCalled()
        })

        it('reports success when postgres cleanup fails after shred', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                status: 'deleted',
                deletedAt: 1700000000,
                deletedBy: 'test@example.com',
            })
            mockPostgres.query.mockRejectedValue(new Error('Postgres down'))

            const result = await service.deleteRecordings(['session-1'], 1, 'test@example.com')

            expect(result).toEqual([
                {
                    sessionId: 'session-1',
                    ok: true,
                    status: 'deleted',
                    deletedAt: 1700000000,
                    deletedBy: 'test@example.com',
                },
            ])
        })

        it('reports success even when all cleanup steps fail', async () => {
            mockKeyStore.deleteKey.mockResolvedValue({
                status: 'deleted',
                deletedAt: 1700000000,
                deletedBy: 'test@example.com',
            })
            mockMetadataStore.storeSessionBlocks.mockRejectedValue(new Error('Kafka down'))
            mockPostgres.query.mockRejectedValue(new Error('Postgres down'))

            const result = await service.deleteRecordings(['session-1'], 1, 'test@example.com')

            expect(result).toEqual([
                {
                    sessionId: 'session-1',
                    ok: true,
                    status: 'deleted',
                    deletedAt: 1700000000,
                    deletedBy: 'test@example.com',
                },
            ])
            expect(mockMetadataStore.storeSessionBlocks).toHaveBeenCalled()
            expect(mockPostgres.query).toHaveBeenCalled()
        })
    })
})

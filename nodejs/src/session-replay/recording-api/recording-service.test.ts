import { NoSuchKey, S3Client } from '@aws-sdk/client-s3'
import { ClickHouseClient } from '@clickhouse/client'
import snappy from 'snappy'

import { PostgresRouter } from '../../utils/db/postgres'
import { SessionFeatureStore } from '../shared/features/session-feature-store'
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
    let mockFeatureStore: jest.Mocked<SessionFeatureStore>
    let mockPostgres: jest.Mocked<PostgresRouter>
    let mockClickhouse: jest.Mocked<ClickHouseClient>

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

        mockFeatureStore = {
            storeSessionFeatures: jest.fn().mockResolvedValue(undefined),
            storeDeletionMarkers: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<SessionFeatureStore>

        mockPostgres = {
            query: jest.fn().mockResolvedValue({ rows: [] }),
        } as unknown as jest.Mocked<PostgresRouter>

        mockClickhouse = {
            query: jest.fn(),
        } as unknown as jest.Mocked<ClickHouseClient>

        service = new RecordingService(
            mockS3Client,
            'test-bucket',
            'session_recordings',
            mockKeyStore,
            mockDecryptor,
            mockMetadataStore,
            mockFeatureStore,
            mockPostgres,
            mockClickhouse
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

        it('returns decompressed data when decompress is true', async () => {
            const originalData = '{"type": 3, "data": {}}'
            const compressed = await snappy.compress(Buffer.from(originalData))
            const mockBody = {
                transformToByteArray: jest.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
            }
            mockS3Send.mockResolvedValue({ Body: mockBody })
            mockDecryptor.decryptBlock.mockResolvedValue({
                data: Buffer.from(compressed),
                sessionState: 'ciphertext',
            })

            const result = await service.getBlock({ ...validParams, decompress: true })

            expect(result).toEqual({ ok: true, data: Buffer.from(originalData) })
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

    describe('parseBlockUrl', () => {
        it.each([
            [
                's3://posthog/session_recordings/30d/1000-abc123?range=bytes=0-5000',
                { key: 'session_recordings/30d/1000-abc123', start_byte: 0, end_byte: 5000 },
            ],
            [
                's3://bucket/session_recordings/90d/2000-def456?range=bytes=100-6000',
                { key: 'session_recordings/90d/2000-def456', start_byte: 100, end_byte: 6000 },
            ],
        ])('parses "%s"', (url, expected) => {
            expect(RecordingService.parseBlockUrl(url)).toEqual(expected)
        })

        it.each([
            ['s3://posthog/key?no-range', 'missing range'],
            ['not-a-url', 'invalid URL'],
        ])('returns null for invalid URL: %s', (url) => {
            expect(RecordingService.parseBlockUrl(url)).toBeNull()
        })
    })

    describe('buildBlockList', () => {
        it('returns sorted blocks when arrays match and first block matches start_time', () => {
            const row = {
                start_time: '2024-01-01 00:00:00.000000',
                block_first_timestamps: ['2024-01-01 00:00:00.000000', '2024-01-01 00:01:00.000000'],
                block_last_timestamps: ['2024-01-01 00:00:59.000000', '2024-01-01 00:01:59.000000'],
                block_urls: [
                    's3://b/session_recordings/30d/1000-aaa?range=bytes=0-100',
                    's3://b/session_recordings/30d/2000-bbb?range=bytes=0-200',
                ],
            }

            const blocks = RecordingService.buildBlockList('sess-1', 1, row)

            expect(blocks).toEqual([
                {
                    key: 'session_recordings/30d/1000-aaa',
                    start_byte: 0,
                    end_byte: 100,
                    start_timestamp: '2024-01-01 00:00:00.000000',
                    end_timestamp: '2024-01-01 00:00:59.000000',
                },
                {
                    key: 'session_recordings/30d/2000-bbb',
                    start_byte: 0,
                    end_byte: 200,
                    start_timestamp: '2024-01-01 00:01:00.000000',
                    end_timestamp: '2024-01-01 00:01:59.000000',
                },
            ])
        })

        it('sorts blocks by start timestamp', () => {
            const row = {
                start_time: '2024-01-01 00:00:00.000000',
                block_first_timestamps: ['2024-01-01 00:01:00.000000', '2024-01-01 00:00:00.000000'],
                block_last_timestamps: ['2024-01-01 00:01:59.000000', '2024-01-01 00:00:59.000000'],
                block_urls: [
                    's3://b/session_recordings/30d/2000-bbb?range=bytes=0-200',
                    's3://b/session_recordings/30d/1000-aaa?range=bytes=0-100',
                ],
            }

            const blocks = RecordingService.buildBlockList('sess-1', 1, row)

            expect(blocks[0]).toEqual({
                key: 'session_recordings/30d/1000-aaa',
                start_byte: 0,
                end_byte: 100,
                start_timestamp: '2024-01-01 00:00:00.000000',
                end_timestamp: '2024-01-01 00:00:59.000000',
            })
            expect(blocks[1]).toEqual({
                key: 'session_recordings/30d/2000-bbb',
                start_byte: 0,
                end_byte: 200,
                start_timestamp: '2024-01-01 00:01:00.000000',
                end_timestamp: '2024-01-01 00:01:59.000000',
            })
        })

        it('returns empty when first block start_time does not match recording start_time', () => {
            const row = {
                start_time: '2024-01-01 00:00:00.000000',
                block_first_timestamps: ['2024-01-01 00:01:00.000000'],
                block_last_timestamps: ['2024-01-01 00:01:59.000000'],
                block_urls: ['s3://b/session_recordings/30d/2000-bbb?range=bytes=0-200'],
            }

            expect(RecordingService.buildBlockList('sess-1', 1, row)).toEqual([])
        })

        it('returns empty when array lengths do not match', () => {
            const row = {
                start_time: '2024-01-01 00:00:00.000000',
                block_first_timestamps: ['2024-01-01 00:00:00.000000'],
                block_last_timestamps: ['2024-01-01 00:00:59.000000', '2024-01-01 00:01:59.000000'],
                block_urls: ['s3://b/session_recordings/30d/1000-aaa?range=bytes=0-100'],
            }

            expect(RecordingService.buildBlockList('sess-1', 1, row)).toEqual([])
        })

        it('returns empty when arrays are empty', () => {
            const row = {
                start_time: '2024-01-01 00:00:00.000000',
                block_first_timestamps: [],
                block_last_timestamps: [],
                block_urls: [],
            }

            expect(RecordingService.buildBlockList('sess-1', 1, row)).toEqual([])
        })

        it('skips blocks with unparseable URLs', () => {
            const row = {
                start_time: '2024-01-01 00:00:00.000000',
                block_first_timestamps: ['2024-01-01 00:00:00.000000', '2024-01-01 00:01:00.000000'],
                block_last_timestamps: ['2024-01-01 00:00:59.000000', '2024-01-01 00:01:59.000000'],
                block_urls: ['s3://b/session_recordings/30d/1000-aaa?range=bytes=0-100', 'not-a-url'],
            }

            const blocks = RecordingService.buildBlockList('sess-1', 1, row)

            expect(blocks).toEqual([
                {
                    key: 'session_recordings/30d/1000-aaa',
                    start_byte: 0,
                    end_byte: 100,
                    start_timestamp: '2024-01-01 00:00:00.000000',
                    end_timestamp: '2024-01-01 00:00:59.000000',
                },
            ])
        })
    })

    describe('listBlocks', () => {
        function mockClickhouseResult(rows: any[]): void {
            mockClickhouse.query.mockResolvedValue({
                json: jest.fn().mockResolvedValue(rows),
            } as any)
        }

        it('returns parsed blocks from ClickHouse result', async () => {
            mockClickhouseResult([
                {
                    start_time: '2024-01-01 00:00:00.000000',
                    block_first_timestamps: ['2024-01-01 00:00:00.000000', '2024-01-01 00:01:00.000000'],
                    block_last_timestamps: ['2024-01-01 00:00:59.000000', '2024-01-01 00:01:59.000000'],
                    block_urls: [
                        's3://b/session_recordings/30d/1000-aaa?range=bytes=0-100',
                        's3://b/session_recordings/30d/2000-bbb?range=bytes=0-200',
                    ],
                },
            ])

            const blocks = await service.listBlocks('sess-1', 1)

            expect(blocks).toEqual([
                {
                    key: 'session_recordings/30d/1000-aaa',
                    start_byte: 0,
                    end_byte: 100,
                    start_timestamp: '2024-01-01 00:00:00.000000',
                    end_timestamp: '2024-01-01 00:00:59.000000',
                },
                {
                    key: 'session_recordings/30d/2000-bbb',
                    start_byte: 0,
                    end_byte: 200,
                    start_timestamp: '2024-01-01 00:01:00.000000',
                    end_timestamp: '2024-01-01 00:01:59.000000',
                },
            ])
            expect(mockClickhouse.query).toHaveBeenCalledWith(
                expect.objectContaining({
                    query_params: { team_id: 1, session_id: 'sess-1' },
                    format: 'JSONEachRow',
                    clickhouse_settings: expect.objectContaining({
                        date_time_output_format: 'iso',
                        log_comment: expect.stringContaining('"team_id":1'),
                        max_execution_time: 30,
                        max_threads: 45,
                        max_bytes_to_read: '10000000000',
                    }),
                })
            )
        })

        it('returns empty array when ClickHouse returns no rows', async () => {
            mockClickhouseResult([])

            const blocks = await service.listBlocks('sess-1', 1)

            expect(blocks).toEqual([])
        })

        it('throws when ClickHouse client is not initialized', async () => {
            const serviceWithoutCH = new RecordingService(
                mockS3Client,
                'test-bucket',
                'session_recordings',
                mockKeyStore,
                mockDecryptor
            )

            await expect(serviceWithoutCH.listBlocks('sess-1', 1)).rejects.toThrow('ClickHouse client not initialized')
        })

        it('propagates ClickHouse query errors', async () => {
            mockClickhouse.query.mockRejectedValue(new Error('Connection refused'))

            await expect(service.listBlocks('sess-1', 1)).rejects.toThrow('Connection refused')
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

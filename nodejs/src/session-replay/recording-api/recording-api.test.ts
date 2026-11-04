import { S3Client } from '@aws-sdk/client-s3'
import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { JWT, PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { getBlockDecryptor, getBlockEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/crypto'
import { getKeyStore } from '~/ingestion/pipelines/sessionreplay/shared/keystore'
import { ReplayEventsOutput, SessionFeaturesOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { RecordingApi } from './recording-api'
import { RecordingService } from './recording-service'
import { KeyStore, RecordingApiConfig, RecordingDecryptor } from './types'

const mockOutputs = {
    queueMessages: jest.fn().mockResolvedValue(undefined),
    produce: jest.fn().mockResolvedValue(undefined),
} as unknown as IngestionOutputs<ReplayEventsOutput | SessionFeaturesOutput>

jest.mock('@clickhouse/client', () => ({
    createClient: jest.fn().mockReturnValue({
        query: jest.fn(),
        close: jest.fn().mockResolvedValue(undefined),
    }),
}))

jest.mock('@aws-sdk/client-s3', () => ({
    S3Client: jest.fn().mockImplementation(() => ({
        send: jest.fn(),
        destroy: jest.fn(),
    })),
    GetObjectCommand: jest.fn().mockImplementation((params) => params),
}))

jest.mock('~/ingestion/pipelines/sessionreplay/shared/keystore', () => ({
    getKeyStore: jest.fn(),
}))

jest.mock('~/ingestion/pipelines/sessionreplay/shared/keystore/cache', () => ({
    MemoryCachedKeyStore: jest.fn().mockImplementation((delegate) => delegate),
    RedisCachedKeyStore: jest.fn().mockImplementation((delegate) => delegate),
}))

jest.mock('~/ingestion/pipelines/sessionreplay/shared/crypto', () => ({
    getBlockDecryptor: jest.fn(),
    getBlockEncryptor: jest.fn(),
}))

jest.mock('~/common/utils/db/redis', () => ({
    createRedisPoolFromConfig: jest.fn().mockReturnValue({
        acquire: jest.fn(),
        release: jest.fn(),
        drain: jest.fn().mockResolvedValue(undefined),
        clear: jest.fn().mockResolvedValue(undefined),
    }),
}))

jest.mock('./recording-service')

describe('RecordingApi', () => {
    let mockConfig: Partial<RecordingApiConfig>
    const mockPostgres = {} as PostgresRouter
    let mockKeyStore: jest.Mocked<KeyStore>
    let mockDecryptor: jest.Mocked<RecordingDecryptor>
    let mockService: jest.Mocked<RecordingService>

    beforeEach(() => {
        jest.clearAllMocks()

        mockConfig = {
            SESSION_RECORDING_V2_S3_REGION: 'us-west-2',
            SESSION_RECORDING_V2_S3_ENDPOINT: undefined,
            SESSION_RECORDING_V2_S3_BUCKET: 'test-bucket',
            SESSION_RECORDING_V2_S3_PREFIX: 'session_recordings',
            SESSION_RECORDING_API_REDIS_HOST: '127.0.0.1',
            SESSION_RECORDING_API_REDIS_PORT: 6379,
            REDIS_POOL_MIN_SIZE: 1,
            REDIS_POOL_MAX_SIZE: 10,
            CLICKHOUSE_HOST: 'localhost',
            CLICKHOUSE_DATABASE: 'default',
            CLICKHOUSE_USER: 'default',
            CLICKHOUSE_PASSWORD: undefined,
            CLICKHOUSE_SECURE: false,
            RECORDING_API_AWS_TIMEOUT_MS: 5000,
            RECORDING_API_REDIS_TIMEOUT_MS: 2000,
        }

        mockKeyStore = {
            start: jest.fn(),
            generateKey: jest.fn(),
            getKey: jest.fn(),
            deleteKey: jest.fn(),
            stop: jest.fn(),
        } as unknown as jest.Mocked<KeyStore>

        mockDecryptor = {
            start: jest.fn().mockResolvedValue(undefined),
            decryptBlock: jest.fn(),
        } as unknown as jest.Mocked<RecordingDecryptor>

        mockService = {
            validateS3Key: jest.fn().mockReturnValue(true),
            formatS3KeyError: jest.fn().mockReturnValue('Invalid key format'),
            getBlock: jest.fn(),
            listBlocks: jest.fn(),
            annotateBlocks: jest
                .fn()
                .mockImplementation((_s: string, _t: number, blocks: unknown) => Promise.resolve(blocks)),
            getBlockByRef: jest.fn(),
            deleteRecordings: jest.fn(),
            encryptBlocks: jest.fn(),
        } as unknown as jest.Mocked<RecordingService>
        ;(getKeyStore as jest.Mock).mockReturnValue(mockKeyStore)
        ;(getBlockDecryptor as jest.Mock).mockReturnValue(mockDecryptor)
        ;(getBlockEncryptor as jest.Mock).mockReturnValue({ start: jest.fn().mockResolvedValue(undefined) })
        ;(RecordingService as unknown as jest.Mock).mockImplementation(() => mockService)
    })

    describe('service', () => {
        it('should return service descriptor', () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres, mockOutputs)
            const service = recordingApi.service

            expect(service.id).toBe('recording-api')
            expect(service.onShutdown).toBeDefined()
            expect(service.healthcheck).toBeDefined()
        })
    })

    describe('start', () => {
        it('should initialize all components', async () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres, mockOutputs)
            await recordingApi.start()

            expect(S3Client).toHaveBeenCalledWith({
                region: 'us-west-2',
                endpoint: undefined,
                forcePathStyle: undefined,
            })
            expect(getKeyStore).toHaveBeenCalledWith('us-west-2', {
                kmsEndpoint: undefined,
                dynamoDBEndpoint: undefined,
                requestTimeoutMs: 5000,
            })
            expect(getBlockDecryptor).toHaveBeenCalled()
            expect(RecordingService).toHaveBeenCalled()
        })

        it('should use default region if not specified', async () => {
            mockConfig.SESSION_RECORDING_V2_S3_REGION = undefined
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres, mockOutputs)

            await recordingApi.start()

            expect(S3Client).toHaveBeenCalledWith({
                region: 'us-east-1',
                endpoint: undefined,
                forcePathStyle: undefined,
            })
        })

        it('should configure forcePathStyle when endpoint is specified', async () => {
            mockConfig.SESSION_RECORDING_V2_S3_ENDPOINT = 'http://s3.test'
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres, mockOutputs)

            await recordingApi.start()

            expect(S3Client).toHaveBeenCalledWith({
                region: 'us-west-2',
                endpoint: 'http://s3.test',
                forcePathStyle: true,
            })
        })
    })

    describe('stop', () => {
        it('should clean up all components', async () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres, mockOutputs)
            await recordingApi.start()
            const s3ClientInstance = (S3Client as jest.Mock).mock.results[0].value

            await recordingApi.stop()

            expect(s3ClientInstance.destroy).toHaveBeenCalled()
            expect(mockKeyStore.stop).toHaveBeenCalled()
        })

        it('should handle stop when not started', async () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres, mockOutputs)
            await expect(recordingApi.stop()).resolves.toBeUndefined()
        })
    })

    describe('isHealthy', () => {
        it('should return error when not started', () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres, mockOutputs)
            const result = recordingApi.isHealthy()

            expect(result.isError()).toBe(true)
        })

        it('should return ok when all components initialized', async () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres, mockOutputs)
            await recordingApi.start()

            const result = recordingApi.isHealthy()

            expect(result.isError()).toBe(false)
        })
    })

    describe('router', () => {
        it('should return an express router', () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres, mockOutputs)
            const router = recordingApi.router()

            expect(router).toBeDefined()
        })
    })

    describe('getBlock endpoint', () => {
        let app: express.Application
        let server: Server
        const validKey = 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee'

        beforeEach(async () => {
            const recordingApi = new RecordingApi({} as RecordingApiConfig, mockPostgres, mockOutputs)
            await recordingApi.start(mockService)
            app = express()
            app.use('/', recordingApi.router())
            server = app.listen(0, () => {})
        })

        afterEach(() => {
            server.close()
        })

        describe('request parsing', () => {
            it('should return 400 if key is missing', async () => {
                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ start_byte: '0', end_byte: '100' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Missing key query parameter' })
            })

            it('should return 400 if start_byte is missing', async () => {
                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: validKey, end_byte: '100' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Missing start_byte query parameter' })
            })

            it('should return 400 if end_byte is missing', async () => {
                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: validKey, start_byte: '0' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Missing end_byte query parameter' })
            })

            it.each([
                ['abc', 'non-numeric string'],
                ['0', 'zero'],
                ['-1', 'negative number'],
            ])('should return 400 for invalid team_id: %s (%s)', async (teamId) => {
                const res = await supertest(app)
                    .get(`/api/projects/${teamId}/recordings/session-123/block`)
                    .query({ key: validKey, start_byte: '0', end_byte: '100' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Invalid team_id parameter' })
            })

            it('should return 400 when start_byte is greater than end_byte', async () => {
                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: validKey, start_byte: '100', end_byte: '50' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'start_byte must be less than or equal to end_byte' })
            })

            it('should return 400 for invalid S3 key', async () => {
                mockService.validateS3Key.mockReturnValue(false)

                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: '../etc/passwd', start_byte: '0', end_byte: '100' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Invalid key format' })
            })

            it('should return 503 if service not initialized', async () => {
                const uninitializedApi = new RecordingApi({} as RecordingApiConfig, mockPostgres, mockOutputs)
                const uninitializedApp = express()
                uninitializedApp.use('/', uninitializedApi.router())
                const uninitializedServer = uninitializedApp.listen(0, () => {})

                try {
                    const res = await supertest(uninitializedApp)
                        .get('/api/projects/1/recordings/session-123/block')
                        .query({ key: validKey, start_byte: '0', end_byte: '100' })

                    expect(res.status).toBe(503)
                    expect(res.body).toEqual({ error: 'S3 client not initialized' })
                } finally {
                    uninitializedServer.close()
                }
            })
        })

        describe('response serialization', () => {
            it('should return decrypted block on success', async () => {
                mockService.getBlock.mockResolvedValue({ ok: true, data: Buffer.from('decrypted data') })

                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: validKey, start_byte: '0', end_byte: '100' })
                    .responseType('buffer')

                expect(res.status).toBe(200)
                expect(res.headers['content-type']).toMatch(/application\/octet-stream/)
                expect(res.headers['content-length']).toBe('14')
                expect(res.headers['cache-control']).toBe('public, max-age=2592000, immutable')
                expect(Buffer.from(res.body)).toEqual(Buffer.from('decrypted data'))
            })

            it('should return 404 for not_found', async () => {
                mockService.getBlock.mockResolvedValue({ ok: false, error: 'not_found' })

                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: validKey, start_byte: '0', end_byte: '100' })

                expect(res.status).toBe(404)
                expect(res.body).toEqual({ error: 'Block not found' })
            })

            it('should return 410 for deleted recording', async () => {
                mockService.getBlock.mockResolvedValue({
                    ok: false,
                    error: 'deleted',
                    deletedAt: 1700000000,
                    deletedBy: 'user@example.com',
                })

                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: validKey, start_byte: '0', end_byte: '100' })

                expect(res.status).toBe(410)
                expect(res.body).toEqual({
                    error: 'recording_deleted',
                    deleted_at: 1700000000,
                    deleted_by: 'user@example.com',
                })
            })

            it('should return 500 when service throws unexpected error', async () => {
                mockService.getBlock.mockRejectedValue(new Error('S3 error'))

                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: validKey, start_byte: '0', end_byte: '100' })

                expect(res.status).toBe(500)
                expect(res.body).toEqual({ error: 'Failed to fetch block from S3' })
            })
        })
    })

    describe('listBlocks endpoint', () => {
        let app: express.Application
        let server: Server

        beforeEach(async () => {
            const recordingApi = new RecordingApi({} as RecordingApiConfig, mockPostgres, mockOutputs)
            await recordingApi.start(mockService)
            app = express()
            app.use('/', recordingApi.router())
            server = app.listen(0, () => {})
        })

        afterEach(() => {
            server.close()
        })

        it('should return blocks from service', async () => {
            mockService.listBlocks.mockResolvedValue([
                {
                    key: 'session_recordings/30d/1000-aaa',
                    start_byte: 0,
                    end_byte: 100,
                    start_timestamp: '2024-01-01T00:00:00Z',
                    end_timestamp: '2024-01-01T00:01:00Z',
                },
                {
                    key: 'session_recordings/30d/2000-bbb',
                    start_byte: 0,
                    end_byte: 200,
                    start_timestamp: '2024-01-01T00:01:00Z',
                    end_timestamp: '2024-01-01T00:02:00Z',
                },
            ])

            const res = await supertest(app).get('/api/projects/1/recordings/session-123/blocks')

            expect(res.status).toBe(200)
            expect(res.body).toEqual({
                blocks: [
                    {
                        key: 'session_recordings/30d/1000-aaa',
                        start_byte: 0,
                        end_byte: 100,
                        start_timestamp: '2024-01-01T00:00:00Z',
                        end_timestamp: '2024-01-01T00:01:00Z',
                    },
                    {
                        key: 'session_recordings/30d/2000-bbb',
                        start_byte: 0,
                        end_byte: 200,
                        start_timestamp: '2024-01-01T00:01:00Z',
                        end_timestamp: '2024-01-01T00:02:00Z',
                    },
                ],
            })
            expect(mockService.listBlocks).toHaveBeenCalledWith('session-123', 1)
        })

        it('returns 410 for a listed session once its key is shredded', async () => {
            mockService.listBlocks.mockResolvedValue([
                {
                    key: 'session_recordings/30d/1000-aaa',
                    start_byte: 0,
                    end_byte: 100,
                    start_timestamp: '2024-01-01T00:00:00Z',
                    end_timestamp: '2024-01-01T00:01:00Z',
                },
            ])
            mockService.annotateBlocks.mockResolvedValue({
                ok: false,
                error: 'deleted',
                deletedAt: 1700000000,
                deletedBy: 'user@example.com',
            })

            const res = await supertest(app).get('/api/projects/1/recordings/session-123/blocks')

            expect(res.status).toBe(410)
            expect(res.body).toEqual({
                error: 'recording_deleted',
                deleted_at: 1700000000,
                deleted_by: 'user@example.com',
            })
            expect(mockService.annotateBlocks).toHaveBeenCalledWith('session-123', 1, expect.any(Array))
        })

        it('still lists blocks when the key store does not answer', async () => {
            mockService.listBlocks.mockResolvedValue([
                {
                    key: 'session_recordings/30d/1000-aaa',
                    start_byte: 0,
                    end_byte: 100,
                    start_timestamp: '2024-01-01T00:00:00Z',
                    end_timestamp: '2024-01-01T00:01:00Z',
                },
            ])
            mockService.annotateBlocks.mockReturnValue(new Promise(() => {}))

            const res = await supertest(app).get('/api/projects/1/recordings/session-123/blocks')

            expect(res.status).toBe(200)
            expect(res.body.blocks).toHaveLength(1)
        })

        it('does not look up the key of a session with no blocks', async () => {
            mockService.listBlocks.mockResolvedValue([])

            const res = await supertest(app).get('/api/projects/1/recordings/session-123/blocks')

            expect(res.status).toBe(200)
            expect(mockService.annotateBlocks).not.toHaveBeenCalled()
        })

        it('still lists blocks when the key store fails', async () => {
            mockService.listBlocks.mockResolvedValue([
                {
                    key: 'session_recordings/30d/1000-aaa',
                    start_byte: 0,
                    end_byte: 100,
                    start_timestamp: '2024-01-01T00:00:00Z',
                    end_timestamp: '2024-01-01T00:01:00Z',
                },
            ])
            mockService.annotateBlocks.mockRejectedValue(new Error('DynamoDB unavailable'))

            const res = await supertest(app).get('/api/projects/1/recordings/session-123/blocks')

            expect(res.status).toBe(200)
            expect(res.body.blocks).toHaveLength(1)
        })

        it('passes block refs through to the listing', async () => {
            const block = {
                key: 'session_recordings/30d/1000-aaa',
                start_byte: 0,
                end_byte: 100,
                start_timestamp: '2024-01-01T00:00:00Z',
                end_timestamp: '2024-01-01T00:01:00Z',
            }
            mockService.listBlocks.mockResolvedValue([block])
            mockService.annotateBlocks.mockResolvedValue([{ ...block, ref: 'v1.abc' }])

            const res = await supertest(app).get('/api/projects/1/recordings/session-123/blocks')

            expect(res.body).toEqual({ blocks: [{ ...block, ref: 'v1.abc' }] })
        })

        it('should return empty blocks when session not found', async () => {
            mockService.listBlocks.mockResolvedValue([])

            const res = await supertest(app).get('/api/projects/1/recordings/session-123/blocks')

            expect(res.status).toBe(200)
            expect(res.body).toEqual({ blocks: [] })
        })

        it('should return 400 for invalid team_id', async () => {
            const res = await supertest(app).get('/api/projects/abc/recordings/session-123/blocks')

            expect(res.status).toBe(400)
        })

        it('should return 500 when service throws', async () => {
            mockService.listBlocks.mockRejectedValue(new Error('ClickHouse error'))

            const res = await supertest(app).get('/api/projects/1/recordings/session-123/blocks')

            expect(res.status).toBe(500)
            expect(res.body).toEqual({ error: 'Failed to list blocks' })
        })

        it('should return 503 if service not initialized', async () => {
            const uninitializedApi = new RecordingApi({} as RecordingApiConfig, mockPostgres, mockOutputs)
            const uninitializedApp = express()
            uninitializedApp.use('/', uninitializedApi.router())
            const uninitializedServer = uninitializedApp.listen(0, () => {})

            try {
                const res = await supertest(uninitializedApp).get('/api/projects/1/recordings/session-123/blocks')

                expect(res.status).toBe(503)
                expect(res.body).toEqual({ error: 'Service not initialized' })
            } finally {
                uninitializedServer.close()
            }
        })
    })

    describe('deleteRecordings endpoint', () => {
        let app: express.Application
        let server: Server

        beforeEach(async () => {
            const recordingApi = new RecordingApi({} as RecordingApiConfig, mockPostgres, mockOutputs)
            await recordingApi.start(mockService)
            app = express()
            app.use(express.json())
            app.use('/', recordingApi.router())
            server = app.listen(0, () => {})
        })

        afterEach(() => {
            server.close()
        })

        describe('request parsing', () => {
            it.each([
                ['abc', 'non-numeric string'],
                ['0', 'zero'],
                ['-1', 'negative number'],
            ])('should return 400 for invalid team_id: %s (%s)', async (teamId) => {
                const res = await supertest(app)
                    .post(`/api/projects/${teamId}/recordings/delete`)
                    .send({ session_ids: ['session-1'], deleted_by: 'user@example.com' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Invalid team_id parameter' })
            })

            it('should return 400 when session_ids is empty', async () => {
                const res = await supertest(app)
                    .post('/api/projects/1/recordings/delete')
                    .send({ session_ids: [], deleted_by: 'user@example.com' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'session_ids must not be empty' })
            })

            it('should return 400 when session_ids is missing', async () => {
                const res = await supertest(app)
                    .post('/api/projects/1/recordings/delete')
                    .send({ deleted_by: 'user@example.com' })

                expect(res.status).toBe(400)
                expect(res.body.error).toBeDefined()
            })

            it('should return 400 when deleted_by is missing', async () => {
                const res = await supertest(app)
                    .post('/api/projects/1/recordings/delete')
                    .send({ session_ids: ['session-1'] })

                expect(res.status).toBe(400)
            })

            it('should return 400 when too many session_ids', async () => {
                const sessionIds = Array.from({ length: 101 }, (_, i) => `session-${i}`)

                const res = await supertest(app)
                    .post('/api/projects/1/recordings/delete')
                    .send({ session_ids: sessionIds, deleted_by: 'user@example.com' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Too many session_ids (max 100)' })
            })

            it('should return 503 if service not initialized', async () => {
                const uninitializedApi = new RecordingApi({} as RecordingApiConfig, mockPostgres, mockOutputs)
                const uninitializedApp = express()
                uninitializedApp.use(express.json())
                uninitializedApp.use('/', uninitializedApi.router())
                const uninitializedServer = uninitializedApp.listen(0, () => {})

                try {
                    const res = await supertest(uninitializedApp)
                        .post('/api/projects/1/recordings/delete')
                        .send({ session_ids: ['session-1'], deleted_by: 'user@example.com' })

                    expect(res.status).toBe(503)
                    expect(res.body).toEqual({ error: 'Service not initialized' })
                } finally {
                    uninitializedServer.close()
                }
            })
        })

        describe('response serialization', () => {
            it('should return result from service', async () => {
                mockService.deleteRecordings.mockResolvedValue([
                    {
                        sessionId: 'session-1',
                        ok: true,
                        status: 'deleted',
                        deletedAt: 1700000000,
                        deletedBy: 'user@example.com',
                    },
                    {
                        sessionId: 'session-2',
                        ok: true,
                        status: 'already_deleted',
                        deletedAt: 1700000000,
                        deletedBy: 'original@example.com',
                    },
                    { sessionId: 'session-3', ok: false, status: 'delete_failed' },
                ])

                const res = await supertest(app)
                    .post('/api/projects/1/recordings/delete')
                    .send({ session_ids: ['session-1', 'session-2', 'session-3'], deleted_by: 'user@example.com' })

                expect(res.status).toBe(200)
                expect(res.body).toEqual([
                    {
                        sessionId: 'session-1',
                        ok: true,
                        status: 'deleted',
                        deletedAt: 1700000000,
                        deletedBy: 'user@example.com',
                    },
                    {
                        sessionId: 'session-2',
                        ok: true,
                        status: 'already_deleted',
                        deletedAt: 1700000000,
                        deletedBy: 'original@example.com',
                    },
                    { sessionId: 'session-3', ok: false, status: 'delete_failed' },
                ])
                expect(mockService.deleteRecordings).toHaveBeenCalledWith(
                    ['session-1', 'session-2', 'session-3'],
                    1,
                    'user@example.com'
                )
            })

            it('should return 500 when service throws unexpected error', async () => {
                mockService.deleteRecordings.mockRejectedValue(new Error('Unexpected error'))

                const res = await supertest(app)
                    .post('/api/projects/1/recordings/delete')
                    .send({ session_ids: ['session-1'], deleted_by: 'user@example.com' })

                expect(res.status).toBe(500)
                expect(res.body).toEqual({ error: 'Failed to delete recordings' })
            })
        })
    })

    describe('encryptBlocks endpoint', () => {
        const JWT_SECRET = 'recording-api-test-secret'
        let app: express.Application
        let server: Server

        const bearer = (op: string, teamId = 1): string =>
            `Bearer ${new JWT(JWT_SECRET).sign({ team_id: teamId, op }, PosthogJwtAudience.RECORDING_API, { expiresIn: '5m' })}`
        const body = { blocks: [Buffer.from('block').toString('base64')], retention_days: 365 }

        beforeEach(async () => {
            const recordingApi = new RecordingApi(
                {
                    RECORDING_API_JWT_SECRET: JWT_SECRET,
                    RECORDING_API_ALLOW_LEGACY_SECRET: false,
                } as RecordingApiConfig,
                mockPostgres,
                mockOutputs
            )
            await recordingApi.start(mockService)
            app = express()
            app.use(express.json())
            app.use('/', recordingApi.router())
            server = app.listen(0, () => {})
            mockService.encryptBlocks.mockResolvedValue({ ok: true, blocks: [Buffer.from('sealed')] })
            mockService.deleteRecordings.mockResolvedValue([])
        })

        afterEach(() => {
            server.close()
        })

        it.each([
            ['encrypt', 'write', 200],
            ['encrypt', 'delete', 403],
            ['encrypt', 'read', 403],
            ['delete', 'write', 403],
        ])('%s route with a %s token returns %s', async (route, op, expectedStatus) => {
            const req =
                route === 'encrypt'
                    ? supertest(app).post('/api/projects/1/recordings/session-1/encrypt').send(body)
                    : supertest(app)
                          .post('/api/projects/1/recordings/delete')
                          .send({ session_ids: ['session-1'], deleted_by: 'user@example.com' })

            const res = await req.set('Authorization', bearer(op))

            expect(res.status).toBe(expectedStatus)
        })

        it('accepts the legacy secret while JWT auth is not configured', async () => {
            const legacyApi = new RecordingApi(
                {
                    RECORDING_API_JWT_SECRET: '',
                    RECORDING_API_ALLOW_LEGACY_SECRET: true,
                    INTERNAL_API_SECRET: 'legacy-secret',
                } as RecordingApiConfig,
                mockPostgres,
                mockOutputs
            )
            await legacyApi.start(mockService)
            const legacyApp = express()
            legacyApp.use(express.json())
            legacyApp.use('/', legacyApi.router())
            const legacyServer = legacyApp.listen(0, () => {})

            try {
                const res = await supertest(legacyApp)
                    .post('/api/projects/1/recordings/session-1/encrypt')
                    .set('X-Internal-Api-Secret', 'legacy-secret')
                    .send(body)

                expect(res.status).toBe(200)
            } finally {
                legacyServer.close()
            }
        })

        it.each([
            [
                { ok: true, blocks: [Buffer.from('sealed')] },
                200,
                { blocks: [Buffer.from('sealed').toString('base64')] },
            ],
            [{ ok: false, error: 'recording_exists' }, 409, { error: 'recording_exists' }],
            [
                { ok: false, error: 'deleted', deletedAt: 1700000000, deletedBy: 'user@example.com' },
                410,
                { error: 'recording_deleted', deleted_at: 1700000000, deleted_by: 'user@example.com' },
            ],
        ])('maps service result %j to %s', async (result, expectedStatus, expectedBody) => {
            mockService.encryptBlocks.mockResolvedValue(result as any)

            const res = await supertest(app)
                .post('/api/projects/1/recordings/session-1/encrypt')
                .set('Authorization', bearer('write'))
                .send(body)

            expect(res.status).toBe(expectedStatus)
            expect(res.body).toEqual(expectedBody)
            expect(mockService.encryptBlocks).toHaveBeenCalledWith('session-1', 1, [Buffer.from('block')], 365)
        })
    })

    describe('browser block route', () => {
        const JWT_SECRET = 'recording-api-test-secret'
        const BLOCKS_JWT_SECRET = 'recording-api-blocks-test-secret'
        const BLOCK_URL = '/replay-blocks/1/session-123/u7/v1.abc'
        let server: Server
        let rateLimiter: { rateLimitGrouped: jest.Mock }

        const browserToken = (
            claims: Record<string, unknown> = {},
            expiresIn: string | null = '5m',
            secret = BLOCKS_JWT_SECRET
        ): string =>
            `Bearer ${new JWT(secret).sign(
                { team_id: 1, session_id: 'session-123', sub: 'u7', tier: 'browser', ...claims },
                PosthogJwtAudience.REPLAY_BLOCKS,
                expiresIn ? { expiresIn } : {}
            )}`
        const serviceToken = (): string =>
            `Bearer ${new JWT(JWT_SECRET).sign({ team_id: 1, op: 'read' }, PosthogJwtAudience.RECORDING_API, { expiresIn: '5m' })}`

        const buildApp = async (role: string, enforced = false): Promise<express.Application> => {
            const recordingApi = new RecordingApi(
                {
                    RECORDING_API_JWT_SECRET: JWT_SECRET,
                    RECORDING_API_BLOCKS_JWT_SECRET: BLOCKS_JWT_SECRET,
                    RECORDING_API_ALLOW_LEGACY_SECRET: false,
                    RECORDING_API_ROLE: role,
                    RECORDING_API_BLOCK_RATE_LIMIT_ENFORCED: enforced,
                } as RecordingApiConfig,
                mockPostgres,
                mockOutputs
            )
            await recordingApi.start(mockService, rateLimiter as any)
            const app = express()
            app.use('/', recordingApi.router())
            server = app.listen(0, () => {})
            return app
        }

        beforeEach(() => {
            rateLimiter = {
                rateLimitGrouped: jest
                    .fn()
                    .mockImplementation((requests: { id: string }[]) =>
                        Promise.resolve(
                            requests.map((r) => [r.id, { isRateLimited: false, tokens: 1, tokensBefore: 2 }])
                        )
                    ),
            }
            mockService.getBlockByRef.mockResolvedValue({ ok: true, data: Buffer.from('block-bytes') })
        })

        afterEach(() => {
            server.close()
        })

        it('serves a block a browser may cache, without the cache varying on cookies', async () => {
            const app = await buildApp('public')

            const res = await supertest(app).get(BLOCK_URL).set('Authorization', browserToken())

            expect(res.status).toBe(200)
            expect(res.headers['cache-control']).toBe('private, max-age=86400, immutable')
            expect(res.headers['vary'] ?? '').not.toMatch(/cookie/i)
            expect(Buffer.from(res.body).toString()).toBe('block-bytes')
            expect(mockService.getBlockByRef).toHaveBeenCalledWith(1, 'session-123', 'v1.abc')
            expect(rateLimiter.rateLimitGrouped).toHaveBeenCalledWith([
                { id: 'viewer:u7', cost: 1, bucketSize: 2000, refillRate: 8 },
            ])
        })

        it.each([
            ['no token', undefined, 401],
            ['a token for another session', () => browserToken({ session_id: 'session-999' }), 403],
            ['a token for another team', () => browserToken({ team_id: 2 }), 403],
            ['a token with no caller', () => browserToken({ sub: undefined }), 403],
            ['a token for another viewer', () => browserToken({ sub: 'u8' }), 403],
            ['a token with a string team', () => browserToken({ team_id: '1' }), 403],
            ['an internal service token', serviceToken, 401],
            ['a browser token signed with the service secret', () => browserToken({}, '5m', JWT_SECRET), 401],
            ['an expired token', () => browserToken({}, '-5m'), 401],
            ['a token that never expires', () => browserToken({}, null), 401],
            [
                'a token issued over two hours ago',
                () => browserToken({ iat: Math.floor(Date.now() / 1000) - 3 * 3600 }, '1d'),
                401,
            ],
        ])('refuses %s', async (_, token, expectedStatus) => {
            const app = await buildApp('public')

            const request = supertest(app).get(BLOCK_URL)
            const res = await (token ? request.set('Authorization', token()) : request)

            expect(res.status).toBe(expectedStatus)
            expect(res.headers['cache-control']).toBe('no-store')
            expect(mockService.getBlockByRef).not.toHaveBeenCalled()
        })

        it('refuses a team id spelled with a leading zero', async () => {
            const app = await buildApp('public')

            const res = await supertest(app)
                .get('/replay-blocks/01/session-123/u7/v1.abc')
                .set('Authorization', browserToken())

            expect(res.status).toBe(403)
        })

        it.each([
            ['deleted', { ok: false, error: 'deleted', deletedAt: 1700000000, deletedBy: 'user@example.com' }, 410],
            ['an unknown ref', { ok: false, error: 'not_found' }, 404],
        ])('answers a block that is %s without caching it', async (_, result, expectedStatus) => {
            mockService.getBlockByRef.mockResolvedValue(result as any)
            const app = await buildApp('public')

            const res = await supertest(app).get(BLOCK_URL).set('Authorization', browserToken())

            expect(res.status).toBe(expectedStatus)
            expect(res.headers['cache-control']).toBe('no-store')
        })

        it.each([
            ['enforced', true, 429],
            ['log only', false, 200],
        ])('applies the per-caller rate limit when %s', async (_, enforced, expectedStatus) => {
            rateLimiter.rateLimitGrouped.mockResolvedValue([
                ['u7', { isRateLimited: true, tokens: -1, tokensBefore: 0 }],
            ])
            const app = await buildApp('public', enforced)

            const res = await supertest(app).get(BLOCK_URL).set('Authorization', browserToken())

            expect(res.status).toBe(expectedStatus)
            expect(res.headers['cache-control']).toBe(enforced ? 'no-store' : 'private, max-age=86400, immutable')
            if (enforced) {
                expect(res.headers['retry-after']).toBe('1')
            }
        })

        it('serves the block when the rate limiter is unavailable', async () => {
            rateLimiter.rateLimitGrouped.mockRejectedValue(new Error('Redis unavailable'))
            const app = await buildApp('public')

            const res = await supertest(app).get(BLOCK_URL).set('Authorization', browserToken())

            expect(res.status).toBe(200)
        })

        it.each([
            ['a browser viewer, by viewer', { tier: 'browser' }, 'viewer:u7', 2000],
            ['a paid API key, by team', { sub: 'k42', tier: 'paid' }, 'team:1', 1200],
            ['another key of the same team, in the same bucket', { sub: 'k43', tier: 'paid' }, 'team:1', 1200],
            ['an enterprise API key, by team', { sub: 'k42', tier: 'enterprise' }, 'team:1', 2000],
            ['a token with no tier, strictest', { sub: 'k42', tier: undefined }, 'team:1', 240],
            ['an unknown tier, strictest', { sub: 'k42', tier: 'platinum' }, 'team:1', 240],
        ])('rate-limits %s', async (_, claims, expectedId, expectedBucketSize) => {
            const app = await buildApp('public')
            const sub = (claims as { sub?: string }).sub ?? 'u7'

            await supertest(app)
                .get(`/replay-blocks/1/session-123/${sub}/v1.abc`)
                .set('Authorization', browserToken(claims))

            expect(rateLimiter.rateLimitGrouped).toHaveBeenCalledWith([
                expect.objectContaining({ id: expectedId, bucketSize: expectedBucketSize }),
            ])
        })

        it.each([
            ['public', 200, 404],
            ['internal', 404, 200],
            ['all', 200, 200],
        ])('a %s process serves only its own routes', async (role, browserStatus, internalStatus) => {
            mockService.listBlocks.mockResolvedValue([])
            const app = await buildApp(role)

            const browser = await supertest(app).get(BLOCK_URL).set('Authorization', browserToken())
            const internal = await supertest(app)
                .get('/api/projects/1/recordings/session-123/blocks')
                .set('Authorization', serviceToken())

            expect(browser.status).toBe(browserStatus)
            expect(internal.status).toBe(internalStatus)
        })
    })
})

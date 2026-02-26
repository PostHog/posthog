import { S3Client } from '@aws-sdk/client-s3'
import { Server } from 'http'
import supertest from 'supertest'
import express from 'ultimate-express'

import { PostgresRouter } from '../../utils/db/postgres'
import { getBlockDecryptor } from '../shared/crypto'
import { getKeyStore } from '../shared/keystore'
import { RetentionService } from '../shared/retention/retention-service'
import { RecordingApi } from './recording-api'
import { RecordingService } from './recording-service'
import { KeyStore, RecordingApiConfig, RecordingDecryptor } from './types'

jest.mock('@aws-sdk/client-s3', () => ({
    S3Client: jest.fn().mockImplementation(() => ({
        send: jest.fn(),
        destroy: jest.fn(),
    })),
    GetObjectCommand: jest.fn().mockImplementation((params) => params),
}))

jest.mock('../shared/keystore', () => ({
    getKeyStore: jest.fn(),
}))

jest.mock('../shared/keystore/cache', () => ({
    MemoryCachedKeyStore: jest.fn().mockImplementation((delegate) => delegate),
    RedisCachedKeyStore: jest.fn().mockImplementation((delegate) => delegate),
}))

jest.mock('../shared/crypto', () => ({
    getBlockDecryptor: jest.fn(),
}))

jest.mock('../../utils/db/redis', () => ({
    createRedisPoolFromConfig: jest.fn().mockReturnValue({
        acquire: jest.fn(),
        release: jest.fn(),
        drain: jest.fn().mockResolvedValue(undefined),
        clear: jest.fn().mockResolvedValue(undefined),
    }),
}))

jest.mock('../../kafka/producer', () => ({
    KafkaProducerWrapper: {
        create: jest.fn().mockResolvedValue({
            produce: jest.fn().mockResolvedValue(undefined),
            disconnect: jest.fn().mockResolvedValue(undefined),
        }),
    },
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
            deleteRecordings: jest.fn(),
        } as unknown as jest.Mocked<RecordingService>
        ;(getKeyStore as jest.Mock).mockReturnValue(mockKeyStore)
        ;(getBlockDecryptor as jest.Mock).mockReturnValue(mockDecryptor)
        ;(RecordingService as jest.Mock).mockImplementation(() => mockService)
    })

    describe('service', () => {
        it('should return service descriptor', () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres)
            const service = recordingApi.service

            expect(service.id).toBe('recording-api')
            expect(service.onShutdown).toBeDefined()
            expect(service.healthcheck).toBeDefined()
        })
    })

    describe('start', () => {
        it('should initialize all components', async () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres)
            await recordingApi.start()

            expect(S3Client).toHaveBeenCalledWith({
                region: 'us-west-2',
                endpoint: undefined,
                forcePathStyle: undefined,
            })
            expect(getKeyStore).toHaveBeenCalledWith(expect.any(RetentionService), 'us-west-2', {
                kmsEndpoint: undefined,
                dynamoDBEndpoint: undefined,
            })
            expect(getBlockDecryptor).toHaveBeenCalledWith(mockKeyStore)
            expect(RecordingService).toHaveBeenCalled()
        })

        it('should use default region if not specified', async () => {
            mockConfig.SESSION_RECORDING_V2_S3_REGION = undefined
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres)

            await recordingApi.start()

            expect(S3Client).toHaveBeenCalledWith({
                region: 'us-east-1',
                endpoint: undefined,
                forcePathStyle: undefined,
            })
        })

        it('should configure forcePathStyle when endpoint is specified', async () => {
            mockConfig.SESSION_RECORDING_V2_S3_ENDPOINT = 'http://localhost:4566'
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres)

            await recordingApi.start()

            expect(S3Client).toHaveBeenCalledWith({
                region: 'us-west-2',
                endpoint: 'http://localhost:4566',
                forcePathStyle: true,
            })
        })
    })

    describe('stop', () => {
        it('should clean up all components', async () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres)
            await recordingApi.start()
            const s3ClientInstance = (S3Client as jest.Mock).mock.results[0].value

            await recordingApi.stop()

            expect(s3ClientInstance.destroy).toHaveBeenCalled()
            expect(mockKeyStore.stop).toHaveBeenCalled()
        })

        it('should handle stop when not started', async () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres)
            await expect(recordingApi.stop()).resolves.toBeUndefined()
        })
    })

    describe('isHealthy', () => {
        it('should return error when not started', () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres)
            const result = recordingApi.isHealthy()

            expect(result.isError()).toBe(true)
        })

        it('should return ok when all components initialized', async () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres)
            await recordingApi.start()

            const result = recordingApi.isHealthy()

            expect(result.isError()).toBe(false)
        })
    })

    describe('router', () => {
        it('should return an express router', () => {
            const recordingApi = new RecordingApi(mockConfig as RecordingApiConfig, mockPostgres)
            const router = recordingApi.router()

            expect(router).toBeDefined()
        })
    })

    describe('getBlock endpoint', () => {
        let app: express.Application
        let server: Server
        const validKey = 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee'

        beforeEach(async () => {
            const recordingApi = new RecordingApi({} as RecordingApiConfig, mockPostgres)
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
                    .query({ start: '0', end: '100' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Missing key query parameter' })
            })

            it('should return 400 if start is missing', async () => {
                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: validKey, end: '100' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Missing start query parameter' })
            })

            it('should return 400 if end is missing', async () => {
                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: validKey, start: '0' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Missing end query parameter' })
            })

            it.each([
                ['abc', 'non-numeric string'],
                ['0', 'zero'],
                ['-1', 'negative number'],
            ])('should return 400 for invalid team_id: %s (%s)', async (teamId) => {
                const res = await supertest(app)
                    .get(`/api/projects/${teamId}/recordings/session-123/block`)
                    .query({ key: validKey, start: '0', end: '100' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Invalid team_id parameter' })
            })

            it('should return 400 when start is greater than end', async () => {
                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: validKey, start: '100', end: '50' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'start must be less than or equal to end' })
            })

            it('should return 400 for invalid S3 key', async () => {
                mockService.validateS3Key.mockReturnValue(false)

                const res = await supertest(app)
                    .get('/api/projects/1/recordings/session-123/block')
                    .query({ key: '../etc/passwd', start: '0', end: '100' })

                expect(res.status).toBe(400)
                expect(res.body).toEqual({ error: 'Invalid key format' })
            })

            it('should return 503 if service not initialized', async () => {
                const uninitializedApi = new RecordingApi({} as RecordingApiConfig, mockPostgres)
                const uninitializedApp = express()
                uninitializedApp.use('/', uninitializedApi.router())
                const uninitializedServer = uninitializedApp.listen(0, () => {})

                try {
                    const res = await supertest(uninitializedApp)
                        .get('/api/projects/1/recordings/session-123/block')
                        .query({ key: validKey, start: '0', end: '100' })

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
                    .query({ key: validKey, start: '0', end: '100' })
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
                    .query({ key: validKey, start: '0', end: '100' })

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
                    .query({ key: validKey, start: '0', end: '100' })

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
                    .query({ key: validKey, start: '0', end: '100' })

                expect(res.status).toBe(500)
                expect(res.body).toEqual({ error: 'Failed to fetch block from S3' })
            })
        })
    })

    describe('deleteRecordings endpoint', () => {
        let app: express.Application
        let server: Server

        beforeEach(async () => {
            const recordingApi = new RecordingApi({} as RecordingApiConfig, mockPostgres)
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
                const uninitializedApi = new RecordingApi({} as RecordingApiConfig, mockPostgres)
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
})

import { S3Client } from '@aws-sdk/client-s3'

import { RetentionService } from '../session-recording/retention/retention-service'
import { TeamService } from '../session-recording/teams/team-service'
import { Hub } from '../types'
import { getBlockDecryptor } from './crypto'
import { getKeyStore } from './keystore'
import { RecordingApi } from './recording-api'
import { RecordingService } from './recording-service'
import { KeyStore, RecordingDecryptor } from './types'

jest.mock('@aws-sdk/client-s3', () => ({
    S3Client: jest.fn().mockImplementation(() => ({
        send: jest.fn(),
        destroy: jest.fn(),
    })),
    GetObjectCommand: jest.fn().mockImplementation((params) => params),
}))

jest.mock('./keystore', () => ({
    getKeyStore: jest.fn(),
}))

jest.mock('./cache', () => ({
    MemoryCachedKeyStore: jest.fn().mockImplementation((delegate) => delegate),
    RedisCachedKeyStore: jest.fn().mockImplementation((delegate) => delegate),
}))

jest.mock('./crypto', () => ({
    getBlockDecryptor: jest.fn(),
}))

jest.mock('../utils/db/redis', () => ({
    createRedisPoolFromConfig: jest.fn().mockReturnValue({
        acquire: jest.fn(),
        release: jest.fn(),
        drain: jest.fn().mockResolvedValue(undefined),
        clear: jest.fn().mockResolvedValue(undefined),
    }),
}))

jest.mock('./recording-service')

describe('RecordingApi', () => {
    let recordingApi: RecordingApi
    let mockHub: Partial<Hub>
    let mockKeyStore: jest.Mocked<KeyStore>
    let mockDecryptor: jest.Mocked<RecordingDecryptor>
    let mockService: jest.Mocked<RecordingService>

    beforeEach(() => {
        jest.clearAllMocks()

        mockHub = {
            SESSION_RECORDING_V2_S3_REGION: 'us-west-2',
            SESSION_RECORDING_V2_S3_ENDPOINT: undefined,
            SESSION_RECORDING_V2_S3_BUCKET: 'test-bucket',
            SESSION_RECORDING_V2_S3_PREFIX: 'session_recordings',
            SESSION_RECORDING_API_REDIS_HOST: '127.0.0.1',
            SESSION_RECORDING_API_REDIS_PORT: 6379,
            REDIS_POOL_MIN_SIZE: 1,
            REDIS_POOL_MAX_SIZE: 10,
            postgres: {} as any,
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
            deleteRecording: jest.fn(),
        } as unknown as jest.Mocked<RecordingService>
        ;(getKeyStore as jest.Mock).mockReturnValue(mockKeyStore)
        ;(getBlockDecryptor as jest.Mock).mockReturnValue(mockDecryptor)
        ;(RecordingService as jest.Mock).mockImplementation(() => mockService)

        recordingApi = new RecordingApi(mockHub as Hub)
    })

    const createMockResponse = () => {
        const jsonMock = jest.fn()
        const setMock = jest.fn()
        const sendMock = jest.fn()
        const statusMock = jest.fn().mockReturnValue({ json: jsonMock })

        return {
            status: statusMock,
            json: jsonMock,
            set: setMock,
            send: sendMock,
            statusMock,
            jsonMock,
            setMock,
            sendMock,
        }
    }

    describe('service', () => {
        it('should return service descriptor', () => {
            const service = recordingApi.service

            expect(service.id).toBe('recording-api')
            expect(service.onShutdown).toBeDefined()
            expect(service.healthcheck).toBeDefined()
        })
    })

    describe('start', () => {
        it('should initialize all components', async () => {
            await recordingApi.start()

            expect(S3Client).toHaveBeenCalledWith({
                region: 'us-west-2',
                endpoint: undefined,
                forcePathStyle: undefined,
            })
            expect(getKeyStore).toHaveBeenCalledWith(
                expect.any(TeamService),
                expect.any(RetentionService),
                'us-west-2',
                {
                    kmsEndpoint: undefined,
                    dynamoDBEndpoint: undefined,
                }
            )
            expect(getBlockDecryptor).toHaveBeenCalledWith(mockKeyStore)
            expect(RecordingService).toHaveBeenCalled()
        })

        it('should use default region if not specified', async () => {
            mockHub.SESSION_RECORDING_V2_S3_REGION = undefined

            await recordingApi.start()

            expect(S3Client).toHaveBeenCalledWith({
                region: 'us-east-1',
                endpoint: undefined,
                forcePathStyle: undefined,
            })
        })

        it('should configure forcePathStyle when endpoint is specified', async () => {
            mockHub.SESSION_RECORDING_V2_S3_ENDPOINT = 'http://localhost:4566'

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
            await recordingApi.start()
            const s3ClientInstance = (S3Client as jest.Mock).mock.results[0].value

            await recordingApi.stop()

            expect(s3ClientInstance.destroy).toHaveBeenCalled()
            expect(mockKeyStore.stop).toHaveBeenCalled()
        })

        it('should handle stop when not started', async () => {
            await expect(recordingApi.stop()).resolves.toBeUndefined()
        })
    })

    describe('isHealthy', () => {
        it('should return error when not started', () => {
            const result = recordingApi.isHealthy()

            expect(result.isError()).toBe(true)
        })

        it('should return ok when all components initialized', async () => {
            await recordingApi.start()

            const result = recordingApi.isHealthy()

            expect(result.isError()).toBe(false)
        })
    })

    describe('router', () => {
        it('should return an express router', () => {
            const router = recordingApi.router()

            expect(router).toBeDefined()
        })
    })

    describe('getBlock endpoint - request parsing', () => {
        it('should return 400 if key is missing', async () => {
            await recordingApi.start()
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { start: '0', end: '100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Missing key query parameter' })
        })

        it('should return 400 if start is missing', async () => {
            await recordingApi.start()
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee', end: '100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Missing start query parameter' })
        })

        it('should return 400 if end is missing', async () => {
            await recordingApi.start()
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee', start: '0' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Missing end query parameter' })
        })

        it.each([
            ['abc', 'non-numeric string'],
            ['0', 'zero'],
            ['-1', 'negative number'],
        ])('should return 400 for invalid team_id: %s (%s)', async (teamId, _description) => {
            await recordingApi.start()
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: teamId, session_id: 'session-123' },
                query: { key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee', start: '0', end: '100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Invalid team_id parameter' })
        })

        it('should return 400 when start is greater than end', async () => {
            await recordingApi.start()
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee', start: '100', end: '50' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'start must be less than or equal to end' })
        })

        it('should return 400 for invalid S3 key', async () => {
            await recordingApi.start()
            mockService.validateS3Key.mockReturnValue(false)

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { key: '../etc/passwd', start: '0', end: '100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Invalid key format' })
        })

        it('should return 503 if service not initialized', async () => {
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee', start: '0', end: '100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(503)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'S3 client not initialized' })
        })
    })

    describe('getBlock endpoint - response serialization', () => {
        it('should return decrypted block on success', async () => {
            await recordingApi.start()
            mockService.getBlock.mockResolvedValue({ ok: true, data: Buffer.from('decrypted data') })

            const { statusMock, setMock, sendMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee', start: '0', end: '100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(setMock).toHaveBeenCalledWith('Content-Type', 'application/octet-stream')
            expect(setMock).toHaveBeenCalledWith('Content-Length', '14')
            expect(setMock).toHaveBeenCalledWith('Cache-Control', 'public, max-age=2592000, immutable')
            expect(sendMock).toHaveBeenCalledWith(Buffer.from('decrypted data'))
        })

        it('should return 404 for not_found', async () => {
            await recordingApi.start()
            mockService.getBlock.mockResolvedValue({ ok: false, error: 'not_found' })

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee', start: '0', end: '100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(404)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Block not found' })
        })

        it('should return 410 for deleted recording', async () => {
            await recordingApi.start()
            mockService.getBlock.mockResolvedValue({ ok: false, error: 'deleted', deletedAt: 1700000000 })

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee', start: '0', end: '100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(410)
            expect(jsonMock).toHaveBeenCalledWith({
                error: 'Recording has been deleted',
                deleted_at: 1700000000,
            })
        })

        it('should return 500 when service throws unexpected error', async () => {
            await recordingApi.start()
            mockService.getBlock.mockRejectedValue(new Error('S3 error'))

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { key: 'session_recordings/30d/1764634738680-3cca0f5d3c7cc7ee', start: '0', end: '100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(500)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Failed to fetch block from S3' })
        })
    })

    describe('deleteRecording endpoint - request parsing', () => {
        it.each([
            ['abc', 'non-numeric string'],
            ['0', 'zero'],
            ['-1', 'negative number'],
        ])('should return 400 for invalid team_id: %s (%s)', async (teamId, _description) => {
            await recordingApi.start()
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: teamId, session_id: 'session-123' },
            }

            await (recordingApi as any).deleteRecording(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Invalid team_id parameter' })
        })

        it('should return 503 if service not initialized', async () => {
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
            }

            await (recordingApi as any).deleteRecording(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(503)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'KeyStore not initialized' })
        })
    })

    describe('deleteRecording endpoint - response serialization', () => {
        it('should return success when key is deleted', async () => {
            await recordingApi.start()
            mockService.deleteRecording.mockResolvedValue({ ok: true })

            const { jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
            }

            await (recordingApi as any).deleteRecording(mockReq, mockRes)

            expect(jsonMock).toHaveBeenCalledWith({ team_id: 1, session_id: 'session-123', status: 'deleted' })
        })

        it('should return 404 when key not found', async () => {
            await recordingApi.start()
            mockService.deleteRecording.mockResolvedValue({ ok: false, error: 'not_found' })

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
            }

            await (recordingApi as any).deleteRecording(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(404)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Recording key not found' })
        })

        it('should return 410 when recording is already deleted', async () => {
            await recordingApi.start()
            mockService.deleteRecording.mockResolvedValue({
                ok: false,
                error: 'already_deleted',
                deletedAt: 1700000000,
            })

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
            }

            await (recordingApi as any).deleteRecording(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(410)
            expect(jsonMock).toHaveBeenCalledWith({
                error: 'Recording has already been deleted',
                deleted_at: 1700000000,
            })
        })

        it('should return 500 when service throws unexpected error', async () => {
            await recordingApi.start()
            mockService.deleteRecording.mockRejectedValue(new Error('Delete error'))

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
            }

            await (recordingApi as any).deleteRecording(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(500)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Failed to delete recording key' })
        })
    })
})

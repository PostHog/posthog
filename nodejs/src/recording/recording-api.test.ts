import { S3Client } from '@aws-sdk/client-s3'

import { Hub } from '../types'
import { BaseKeyStore } from './keystore'
import { getKeyStore } from './keystore'
import { RecordingApi } from './recording-api'
import { BaseRecordingDecryptor } from './recording-io'
import { getBlockDecryptor } from './recording-io'

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

jest.mock('./recording-io', () => ({
    getBlockDecryptor: jest.fn(),
}))

describe('RecordingApi', () => {
    let recordingApi: RecordingApi
    let mockHub: Partial<Hub>
    let mockKeyStore: jest.Mocked<BaseKeyStore>
    let mockDecryptor: jest.Mocked<BaseRecordingDecryptor>

    beforeEach(() => {
        jest.clearAllMocks()

        mockHub = {
            SESSION_RECORDING_V2_S3_REGION: 'us-west-2',
            SESSION_RECORDING_V2_S3_ENDPOINT: undefined,
        }

        mockKeyStore = {
            generateKey: jest.fn(),
            getKey: jest.fn(),
            deleteKey: jest.fn(),
            destroy: jest.fn(),
        } as unknown as jest.Mocked<BaseKeyStore>

        mockDecryptor = {
            decryptBlock: jest.fn(),
        } as unknown as jest.Mocked<BaseRecordingDecryptor>
        ;(getKeyStore as jest.Mock).mockResolvedValue(mockKeyStore)
        ;(getBlockDecryptor as jest.Mock).mockResolvedValue(mockDecryptor)

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
            expect(getKeyStore).toHaveBeenCalledWith(mockHub, 'us-west-2')
            expect(getBlockDecryptor).toHaveBeenCalledWith(mockKeyStore)
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
            expect(mockKeyStore.destroy).toHaveBeenCalled()
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

    describe('getBlock endpoint', () => {
        it('should return 400 if uri is missing', async () => {
            await recordingApi.start()
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: {},
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Missing or invalid uri query parameter' })
        })

        it('should return 400 if uri is not a string', async () => {
            await recordingApi.start()
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { uri: 123 },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Missing or invalid uri query parameter' })
        })

        it('should return 400 if uri has invalid protocol', async () => {
            await recordingApi.start()
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { uri: 'http://my-bucket/path?range=bytes=0-100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({
                error: 'Invalid S3 URI format. Expected: s3://bucket/key?range=bytes=start-end (range is required)',
            })
        })

        it('should return 400 if range is missing', async () => {
            await recordingApi.start()
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { uri: 's3://my-bucket/path/to/file' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(400)
            expect(jsonMock).toHaveBeenCalledWith({
                error: 'Invalid S3 URI format. Expected: s3://bucket/key?range=bytes=start-end (range is required)',
            })
        })

        it('should return 503 if S3 client not initialized', async () => {
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { uri: 's3://my-bucket/path/to/file?range=bytes=0-100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(503)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'S3 client not initialized' })
        })

        it('should return 404 if S3 returns no body', async () => {
            await recordingApi.start()
            const s3ClientInstance = (S3Client as jest.Mock).mock.results[0].value
            s3ClientInstance.send.mockResolvedValue({ Body: null })

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { uri: 's3://my-bucket/path/to/file?range=bytes=0-100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(404)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Block not found' })
        })

        it('should return decrypted block on success', async () => {
            await recordingApi.start()
            const s3ClientInstance = (S3Client as jest.Mock).mock.results[0].value
            const mockBody = {
                transformToByteArray: jest.fn().mockResolvedValue(new Uint8Array([1, 2, 3])),
            }
            s3ClientInstance.send.mockResolvedValue({ Body: mockBody })
            mockDecryptor.decryptBlock.mockResolvedValue(Buffer.from('decrypted data'))

            const { statusMock, jsonMock, setMock, sendMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { uri: 's3://my-bucket/path/to/file?range=bytes=0-100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(mockDecryptor.decryptBlock).toHaveBeenCalledWith('session-123', 1, expect.any(Buffer))
            expect(setMock).toHaveBeenCalledWith('Content-Type', 'application/octet-stream')
            expect(setMock).toHaveBeenCalledWith('Content-Length', '14')
            expect(sendMock).toHaveBeenCalledWith(Buffer.from('decrypted data'))
        })

        it('should return 500 if S3 fetch fails', async () => {
            await recordingApi.start()
            const s3ClientInstance = (S3Client as jest.Mock).mock.results[0].value
            s3ClientInstance.send.mockRejectedValue(new Error('S3 error'))

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
                query: { uri: 's3://my-bucket/path/to/file?range=bytes=0-100' },
            }

            await (recordingApi as any).getBlock(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(500)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Failed to fetch block from S3' })
        })
    })

    describe('deleteRecording endpoint', () => {
        it('should return 503 if keyStore not initialized', async () => {
            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
            }

            await (recordingApi as any).deleteRecording(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(503)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'KeyStore not initialized' })
        })

        it('should return success when key is deleted', async () => {
            await recordingApi.start()
            mockKeyStore.deleteKey.mockResolvedValue(true)

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
            }

            await (recordingApi as any).deleteRecording(mockReq, mockRes)

            expect(mockKeyStore.deleteKey).toHaveBeenCalledWith('session-123', 1)
            expect(jsonMock).toHaveBeenCalledWith({ team_id: '1', session_id: 'session-123', status: 'deleted' })
        })

        it('should return 404 when key not found', async () => {
            await recordingApi.start()
            mockKeyStore.deleteKey.mockResolvedValue(false)

            const { statusMock, jsonMock, ...mockRes } = createMockResponse()
            const mockReq = {
                params: { team_id: '1', session_id: 'session-123' },
            }

            await (recordingApi as any).deleteRecording(mockReq, mockRes)

            expect(statusMock).toHaveBeenCalledWith(404)
            expect(jsonMock).toHaveBeenCalledWith({ error: 'Recording key not found' })
        })

        it('should return 500 when delete fails', async () => {
            await recordingApi.start()
            mockKeyStore.deleteKey.mockRejectedValue(new Error('Delete error'))

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

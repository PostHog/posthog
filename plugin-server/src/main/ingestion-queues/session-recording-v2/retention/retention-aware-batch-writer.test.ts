import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'

import { TeamId } from '../../../../types'
import { RetentionAwareStorage } from './retention-aware-batch-writer'
import { RetentionService } from './retention-service'

jest.mock('@aws-sdk/lib-storage')
jest.mock('../../../../utils/logger')

jest.setTimeout(1000)

describe('RetentionAwareStorage', () => {
    let storage: RetentionAwareStorage
    let mockUpload: jest.Mock
    let mockUploadDone: jest.Mock
    let uploadedData: Buffer
    let mockS3Client: jest.Mocked<S3Client>
    let mockRetentionService: jest.Mocked<RetentionService>

    beforeEach(() => {
        uploadedData = Buffer.alloc(0)
        mockS3Client = {} as jest.Mocked<S3Client>

        mockUpload = jest.fn().mockImplementation(({ params: { Body: stream } }) => {
            const done = async () => {
                return new Promise((resolve, reject) => {
                    stream.on('data', (chunk: any) => {
                        uploadedData = Buffer.concat([uploadedData, chunk])
                    })
                    stream.on('error', reject)
                    stream.on('end', resolve)
                })
            }

            mockUploadDone = jest.fn().mockImplementation(done)
            return { done: mockUploadDone }
        })
        jest.mocked(Upload).mockImplementation(mockUpload)

        mockRetentionService = {
            getSessionRetention: jest.fn().mockImplementation((teamId: TeamId, sessionId: string) => {
                const sessionKey = `${teamId}$${sessionId}`
                return {
                    '1$123': '1y',
                    '2$456': '90d',
                }[sessionKey]
            }),
        } as unknown as jest.Mocked<RetentionService>

        storage = new RetentionAwareStorage(mockS3Client, 'test-bucket', 'test-prefix', 5000, mockRetentionService)
    })

    afterEach(() => {
        jest.clearAllMocks()
        uploadedData = Buffer.alloc(0)
    })

    describe('writeSession', () => {
        it('should write session data to correct retention prefix and return bytes written with URL', async () => {
            const writer = storage.newBatch()
            const testData = Buffer.from('test data')
            const result = await writer.writeSession({ buffer: testData, teamId: 1, sessionId: '123' })

            expect(mockUpload).toHaveBeenCalledTimes(1)
            expect(mockUpload).toHaveBeenCalledWith(
                expect.objectContaining({
                    client: mockS3Client,
                    params: expect.objectContaining({
                        Bucket: 'test-bucket',
                        ContentType: 'application/octet-stream',
                    }),
                })
            )

            await writer.finish()

            expect(uploadedData.toString()).toBe(testData.toString())
            expect(result.bytesWritten).toBe(testData.length)
            expect(result.url).toMatch(/^s3:\/\/test-bucket\/test-prefix\/1y\/\d+-[a-z0-9]+\?range=bytes=0-\d+$/)
        })

        it('should handle successful upload completion', async () => {
            const writer = storage.newBatch()
            const testData = Buffer.from('test data\nmore test data\n')

            const result = await writer.writeSession({ buffer: testData, teamId: 2, sessionId: '456' })
            await writer.finish()

            expect(mockUpload).toHaveBeenCalledTimes(1)
            expect(mockUploadDone).toHaveBeenCalled()
            expect(uploadedData.toString()).toBe(testData.toString())
            expect(result.url).toMatch(/^s3:\/\/test-bucket\/test-prefix\/90d\/\d+-[a-z0-9]+\?range=bytes=0-\d+$/)
        })
    })

    describe('checkHealth', () => {
        it('should return true when bucket is accessible', async () => {
            mockS3Client.send = jest.fn().mockResolvedValue({})

            const result = await storage.checkHealth()

            expect(result).toBe(true)
            expect(mockS3Client.send).toHaveBeenCalledWith(
                expect.objectContaining({
                    input: { Bucket: 'test-bucket' },
                })
            )
        })

        it('should return false when bucket is not accessible', async () => {
            mockS3Client.send = jest.fn().mockRejectedValue(new Error('Bucket not found'))

            const result = await storage.checkHealth()

            expect(result).toBe(false)
            expect(mockS3Client.send).toHaveBeenCalledWith(
                expect.objectContaining({
                    input: { Bucket: 'test-bucket' },
                })
            )
        })
    })
})

import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'

import { S3SessionBatchFileStorage } from './s3-session-batch-writer'

jest.mock('@aws-sdk/lib-storage')
jest.mock('../../../../utils/status')

describe('S3SessionBatchFileStorage', () => {
    let storage: S3SessionBatchFileStorage
    let mockUpload: jest.Mock
    let mockUploadDone: jest.Mock
    let uploadedData: Buffer
    let mockS3Client: jest.Mocked<S3Client>

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

        storage = new S3SessionBatchFileStorage(mockS3Client, 'test-bucket', 'test-prefix')
    })

    afterEach(() => {
        jest.clearAllMocks()
        uploadedData = Buffer.alloc(0)
    })

    describe('writeSession', () => {
        it('should write session data and return bytes written with URL', async () => {
            const writer = storage.newBatch()
            const testData = Buffer.from('test data')
            const result = await writer.writeSession(testData)

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
            expect(result.url).toMatch(/^s3:\/\/test-bucket\/test-prefix\/\d+-[a-z0-9]+\?range=bytes=0-\d+$/)
        })

        it('should handle successful upload completion', async () => {
            const writer = storage.newBatch()
            const testData = Buffer.from('test data\nmore test data\n')

            const result = await writer.writeSession(testData)
            await writer.finish()

            expect(mockUpload).toHaveBeenCalledTimes(1)
            expect(mockUploadDone).toHaveBeenCalled()
            expect(uploadedData.toString()).toBe(testData.toString())
            expect(result.url).toMatch(/^s3:\/\/test-bucket\/test-prefix\/\d+-[a-z0-9]+\?range=bytes=0-\d+$/)
        })

        it('should handle upload errors', async () => {
            const testError = new Error('Upload failed')

            mockUpload.mockImplementationOnce(({ params: { Body: stream } }) => {
                stream.write = () => {
                    process.nextTick(() => {
                        stream.emit('error', testError)
                    })
                    return false
                }

                return {
                    done: jest.fn().mockResolvedValue(undefined),
                }
            })

            const writer = storage.newBatch()

            const testData = Buffer.from('test data')
            await expect(writer.writeSession(testData)).rejects.toThrow(testError)
        })

        it('should handle writing large amounts of data', async () => {
            const writer = storage.newBatch()
            const chunk = Buffer.alloc(1024 * 1024 * 100, 'x') // 100MB

            const result = await writer.writeSession(chunk)
            await writer.finish()

            expect(mockUpload).toHaveBeenCalledTimes(1)
            expect(mockUploadDone).toHaveBeenCalled()
            expect(uploadedData.length).toBe(1024 * 1024 * 100)
            // toEqual is slow for large buffers, so we use Buffer.compare instead
            expect(Buffer.compare(uploadedData as any, chunk as any)).toBe(0)
            expect(result.url).toMatch(/^s3:\/\/test-bucket\/test-prefix\/\d+-[a-z0-9]+\?range=bytes=0-\d+$/)
        })

        it('should handle multiple writes before stream end', async () => {
            const writer = storage.newBatch()
            const lines = ['line1\n', 'line2\n', 'line3\n']

            for (const line of lines) {
                await writer.writeSession(Buffer.from(line))
            }
            await writer.finish()

            expect(uploadedData.toString()).toBe(lines.join(''))
            expect(mockUpload).toHaveBeenCalledTimes(1)
        })

        it('should generate unique keys for each upload', () => {
            const keys = new Set()
            const iterations = 100

            for (let i = 0; i < iterations; i++) {
                storage.newBatch()
                const uploadCall = mockUpload.mock.calls[i][0]
                const key = uploadCall.params.Key
                keys.add(key)
            }

            expect(keys.size).toBe(iterations)
            for (const key of keys) {
                expect(key).toMatch(/^test-prefix\/\d+-[a-z0-9]+$/)
            }
        })
    })
})

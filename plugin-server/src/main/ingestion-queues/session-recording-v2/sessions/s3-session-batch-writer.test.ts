import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'

import { SessionBatchMetrics } from './metrics'
import { S3SessionBatchFileStorage } from './s3-session-batch-writer'

jest.mock('@aws-sdk/lib-storage')
jest.mock('../../../../utils/logger')
jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementS3BatchesStarted: jest.fn(),
        incrementS3BatchesUploaded: jest.fn(),
        incrementS3UploadErrors: jest.fn(),
        incrementS3UploadTimeouts: jest.fn(),
        incrementS3BytesWritten: jest.fn(),
        observeS3UploadLatency: jest.fn(),
    },
}))

jest.setTimeout(1000)

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

        storage = new S3SessionBatchFileStorage(mockS3Client, 'test-bucket', 'test-prefix', 5000)
    })

    afterEach(() => {
        jest.clearAllMocks()
        uploadedData = Buffer.alloc(0)
    })

    describe('writeSession', () => {
        it('should write session data and return bytes written with URL', async () => {
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
            expect(result.url).toMatch(/^s3:\/\/test-bucket\/test-prefix\/\d+-[a-z0-9]+\?range=bytes=0-\d+$/)
        })

        it('should handle successful upload completion', async () => {
            const writer = storage.newBatch()
            const testData = Buffer.from('test data\nmore test data\n')

            const result = await writer.writeSession({ buffer: testData, teamId: 1, sessionId: '123' })
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
            await expect(writer.writeSession({ buffer: testData, teamId: 1, sessionId: '123' })).rejects.toThrow(
                testError
            )
        })

        it('should handle writing large amounts of data', async () => {
            const writer = storage.newBatch()
            const chunk = Buffer.alloc(1024 * 1024 * 100, 'x') // 100MB

            const result = await writer.writeSession({ buffer: chunk, teamId: 1, sessionId: '123' })
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
                await writer.writeSession({ buffer: Buffer.from(line), teamId: 1, sessionId: '123' })
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

    describe('metrics', () => {
        it('should increment batches started when creating a new batch', () => {
            storage.newBatch()

            expect(SessionBatchMetrics.incrementS3BatchesStarted).toHaveBeenCalledTimes(1)
        })

        it('should increment batches uploaded and observe metrics on successful finish', async () => {
            const writer = storage.newBatch()
            const testData = Buffer.from('test data')

            await writer.writeSession({ buffer: testData, teamId: 1, sessionId: '123' })
            await writer.finish()

            expect(SessionBatchMetrics.incrementS3BatchesUploaded).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.observeS3UploadLatency).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementS3BytesWritten).toHaveBeenCalledWith(testData.length)
        })

        it('should increment upload errors when stream errors occur', async () => {
            const testError = new Error('Stream error')

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

            await expect(writer.writeSession({ buffer: testData, teamId: 1, sessionId: '123' })).rejects.toThrow(
                testError
            )

            expect(SessionBatchMetrics.incrementS3UploadErrors).toHaveBeenCalledTimes(1)
        })

        it('should observe correct latency and bytes written for successful upload', async () => {
            jest.useFakeTimers()

            const writer = storage.newBatch()
            const testData = Buffer.from('test data')

            await writer.writeSession({ buffer: testData, teamId: 1, sessionId: '123' })

            // Advance time to simulate some upload duration
            jest.advanceTimersByTime(100)

            await writer.finish()

            expect(SessionBatchMetrics.observeS3UploadLatency).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementS3BytesWritten).toHaveBeenCalledWith(testData.length)

            // Verify latency is a positive number (should be 0.1 seconds due to our timer advance)
            const latencyCall = (SessionBatchMetrics.observeS3UploadLatency as jest.Mock).mock.calls[0][0]
            expect(latencyCall).toBeGreaterThan(0)

            jest.useRealTimers()
        })

        it('should track multiple batches correctly', () => {
            storage.newBatch()
            storage.newBatch()

            expect(SessionBatchMetrics.incrementS3BatchesStarted).toHaveBeenCalledTimes(2)
        })
    })

    describe('timeout', () => {
        beforeEach(() => {
            jest.useFakeTimers()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('should timeout if upload takes too long', async () => {
            // Mock a slow upload that never resolves
            mockUpload = jest.fn().mockImplementation((_) => {
                const done = async () => {
                    return new Promise(() => {})
                }

                mockUploadDone = jest.fn().mockImplementation(done)
                return { done: mockUploadDone }
            })
            jest.mocked(Upload).mockImplementation(mockUpload)

            const writer = storage.newBatch()
            const testData = Buffer.from('test data')
            await writer.writeSession({ buffer: testData, teamId: 1, sessionId: '123' })

            const finishPromise = writer.finish()

            // Advance timers past the default 5s timeout
            jest.advanceTimersByTime(6000)

            await expect(finishPromise).rejects.toThrow('S3 upload timed out after 5000ms')
        })

        it('should increment timeout metric when upload times out', async () => {
            // Mock a slow upload that never resolves
            mockUpload.mockImplementationOnce(() => ({
                done: () => new Promise(() => {}),
            }))

            const writer = storage.newBatch()
            const testData = Buffer.from('test data')
            await writer.writeSession({ buffer: testData, teamId: 1, sessionId: '123' })

            const finishPromise = writer.finish()

            // Advance timers past the timeout
            jest.advanceTimersByTime(6000)

            await expect(finishPromise).rejects.toThrow('S3 upload timed out after 5000ms')
            expect(SessionBatchMetrics.incrementS3UploadTimeouts).toHaveBeenCalledTimes(1)
        })

        it('should clear timeout on successful upload', async () => {
            const writer = storage.newBatch()
            const testData = Buffer.from('test data')
            await writer.writeSession({ buffer: testData, teamId: 1, sessionId: '123' })
            await writer.finish()

            // Advance timers - should not throw since timeout was cleared
            jest.advanceTimersByTime(6000)
        })

        it('should respect custom timeout value', async () => {
            // Mock a slow upload that never resolves
            mockUpload.mockImplementationOnce(() => ({
                done: () => new Promise(() => {}),
            }))

            const customTimeout = 2000
            storage = new S3SessionBatchFileStorage(mockS3Client, 'test-bucket', 'test-prefix', customTimeout)
            const writer = storage.newBatch()
            const testData = Buffer.from('test data')
            await writer.writeSession({ buffer: testData, teamId: 1, sessionId: '123' })

            const finishPromise = writer.finish()

            // Advance timers just before timeout
            jest.advanceTimersByTime(1999)

            // Advance past timeout
            jest.advanceTimersByTime(2)
            await expect(finishPromise).rejects.toThrow('S3 upload timed out after 2000ms')
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

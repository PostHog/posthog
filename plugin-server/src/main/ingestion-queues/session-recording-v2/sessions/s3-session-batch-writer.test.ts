import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'

import { status } from '../../../../utils/status'
import { S3SessionBatchWriter } from './s3-session-batch-writer'

jest.mock('@aws-sdk/lib-storage')
jest.mock('../../../../utils/status')

describe('S3SessionBatchWriter', () => {
    let writer: S3SessionBatchWriter
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
                    stream.on('data', (chunk) => {
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

        writer = new S3SessionBatchWriter(mockS3Client, 'test-bucket', 'test-prefix')
    })

    afterEach(() => {
        jest.clearAllMocks()
        uploadedData = Buffer.alloc(0)
    })

    describe('open()', () => {
        it('should pass the returned stream as the S3 upload body', () => {
            const { stream } = writer.newBatch()

            expect(mockUpload).toHaveBeenCalledTimes(1)
            expect(mockUpload).toHaveBeenCalledWith(
                expect.objectContaining({
                    client: mockS3Client,
                    params: expect.objectContaining({
                        Body: stream,
                        Bucket: 'test-bucket',
                    }),
                })
            )
        })

        it('should handle successful upload completion', async () => {
            const { stream, finish } = writer.newBatch()
            const testData = 'test data\nmore test data\n'

            stream.write(testData)
            stream.end()

            await finish()

            expect(mockUpload).toHaveBeenCalledTimes(1)
            expect(mockUploadDone).toHaveBeenCalled()
            expect(uploadedData.toString()).toBe(testData)
            expect(status.info).toHaveBeenCalledWith(
                '🔄',
                's3_session_batch_writer_upload_complete',
                expect.objectContaining({
                    key: expect.stringMatching(/^test-prefix\/\d+-[a-z0-9]+$/),
                })
            )
        })

        it('should handle upload errors', async () => {
            const testError = new Error('Upload failed')

            const { stream, finish } = writer.newBatch()

            stream.emit('error', testError)
            stream.end()

            await expect(finish()).rejects.toThrow(testError)

            expect(status.error).toHaveBeenCalledWith(
                '🔄',
                's3_session_batch_writer_upload_error',
                expect.objectContaining({
                    error: testError,
                    key: expect.stringMatching(/^test-prefix\/\d+-[a-z0-9]+$/),
                })
            )
        })

        it('should handle writing large amounts of data', async () => {
            const { stream, finish } = writer.newBatch()

            // Write 100MB of data
            const chunk = Buffer.alloc(1024 * 1024 * 100, 'x')
            stream.write(chunk)
            stream.end()

            await finish()

            expect(mockUpload).toHaveBeenCalledTimes(1)
            expect(mockUploadDone).toHaveBeenCalled()
            expect(uploadedData.length).toBe(1024 * 1024 * 100)
            // toEqual is slow for large buffers, so we use Buffer.compare instead
            expect(Buffer.compare(uploadedData as any, chunk as any)).toBe(0)
            expect(status.info).toHaveBeenCalledWith(
                '🔄',
                's3_session_batch_writer_upload_complete',
                expect.objectContaining({
                    key: expect.stringMatching(/^test-prefix\/\d+-[a-z0-9]+$/),
                })
            )
        })

        it('should handle multiple writes before stream end', async () => {
            const { stream, finish } = writer.newBatch()
            const lines = ['line1\n', 'line2\n', 'line3\n']

            for (const line of lines) {
                stream.write(line)
            }
            stream.end()

            await finish()

            expect(uploadedData.toString()).toBe(lines.join(''))
            expect(mockUpload).toHaveBeenCalledTimes(1)
        })

        it('should generate unique keys for each upload', () => {
            const keys = new Set()
            const iterations = 100

            for (let i = 0; i < iterations; i++) {
                writer.newBatch()
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

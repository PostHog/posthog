import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import { Readable } from 'stream'

import { status } from '../../../../utils/status'
import { S3SessionBatchWriter } from './s3-session-batch-writer'

jest.mock('@aws-sdk/client-s3')
jest.mock('@aws-sdk/lib-storage')
jest.mock('../../../../utils/status')

describe('S3SessionBatchWriter', () => {
    let writer: S3SessionBatchWriter
    let mockUpload: jest.Mock
    let mockUploadDone: jest.Mock
    let uploadedData: Buffer

    beforeEach(() => {
        uploadedData = Buffer.alloc(0)
        jest.mocked(S3Client).mockImplementation(() => ({} as any))
        mockUploadDone = jest.fn().mockImplementation(async () => {
            const stream = mockUpload.mock.calls[0][0].params.Body as Readable
            for await (const chunk of stream) {
                uploadedData = Buffer.concat([uploadedData, chunk])
            }
        })
        mockUpload = jest.fn().mockImplementation(() => ({
            done: mockUploadDone,
        }))
        jest.mocked(Upload).mockImplementation((args) => {
            mockUpload(args)
            return { done: mockUploadDone } as unknown as Upload
        })

        writer = new S3SessionBatchWriter({
            bucket: 'test-bucket',
            prefix: 'test-prefix',
            region: 'test-region',
        })
    })

    afterEach(() => {
        jest.clearAllMocks()
        uploadedData = Buffer.alloc(0)
    })

    it('should create an S3 client with the correct config', () => {
        expect(S3Client).toHaveBeenCalledWith({ region: 'test-region' })
        expect(status.info).toHaveBeenCalledWith('🔄', 's3_session_batch_writer_created', {
            bucket: 'test-bucket',
            prefix: 'test-prefix',
        })
    })

    describe('open()', () => {
        it('should pass the returned stream as the S3 upload body', () => {
            const { stream } = writer.newBatch()

            expect(mockUpload).toHaveBeenCalledTimes(1)
            expect(mockUpload).toHaveBeenCalledWith(
                expect.objectContaining({
                    params: expect.objectContaining({
                        Body: stream,
                    }),
                })
            )
        })

        it('should handle successful upload completion', async () => {
            const { stream, finish } = writer.newBatch()
            const testData = 'test data\nmore test data\n'

            // Write some data and finish
            stream.write(testData)
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
            mockUploadDone.mockRejectedValue(testError)

            const { stream, finish } = writer.newBatch()
            const testData = 'error test data\n'

            // Write some data and try to finish
            stream.write(testData)
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

        it('should handle multiple writes before finish', async () => {
            const { stream, finish } = writer.newBatch()
            const lines = ['line1\n', 'line2\n', 'line3\n']

            for (const line of lines) {
                stream.write(line)
            }
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

            // All keys should be unique
            expect(keys.size).toBe(iterations)
            // All keys should match our expected format
            for (const key of keys) {
                expect(key).toMatch(/^test-prefix\/\d+-[a-z0-9]+$/)
            }
        })
    })
})

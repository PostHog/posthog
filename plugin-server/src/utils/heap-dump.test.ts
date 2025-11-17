import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import { Readable } from 'stream'

import { PluginsServerConfig } from '../types'
import { createHeapDump, initializeHeapDump } from './heap-dump'

jest.mock('@aws-sdk/lib-storage')
jest.mock('v8', () => ({
    getHeapSnapshot: jest.fn(() => {
        const mockSnapshot =
            '{"snapshot":{"meta":{"node_fields":["type","name","id","self_size","edge_count","trace_node_id"],"node_types":[["hidden","array","string","object","code","closure","regexp","number","native","synthetic","concatenated string","sliced string","symbol","bigint"],"bigint"],"edge_fields":["type","name_or_index","to_node"],"edge_types":[["context","element","property","internal","hidden","shortcut","weak"]]},"node_count":1,"edge_count":0},"nodes":[0,0,0,0,0,0],"edges":[],"strings":[""]}'
        return Readable.from([Buffer.from(mockSnapshot)])
    }),
    getHeapStatistics: jest.fn(() => ({
        total_heap_size: 100000000,
        total_heap_size_executable: 5000000,
        total_physical_size: 80000000,
        total_available_size: 1500000000,
        used_heap_size: 70000000,
        heap_size_limit: 2000000000,
        malloced_memory: 8000000,
        peak_malloced_memory: 10000000,
        does_zap_garbage: 0,
        number_of_native_contexts: 2,
        number_of_detached_contexts: 0,
        total_global_handles_size: 16384,
        used_global_handles_size: 8192,
        external_memory: 20000000,
    })),
}))

jest.setTimeout(1000)

describe('heap-dump', () => {
    let s3Client: jest.Mocked<S3Client>
    let config: PluginsServerConfig
    let mockUpload: jest.Mock
    let mockUploadDone: jest.Mock
    let processOnSpy: jest.SpyInstance
    let uploadedData: Buffer

    beforeEach(() => {
        uploadedData = Buffer.alloc(0)
        s3Client = {} as jest.Mocked<S3Client>

        config = {
            HEAP_DUMP_ENABLED: true,
            HEAP_DUMP_S3_BUCKET: 'test-heap-dumps',
            HEAP_DUMP_S3_PREFIX: 'heap-dumps',
            HEAP_DUMP_S3_REGION: 'us-east-1',
        } as PluginsServerConfig

        mockUpload = jest.fn().mockImplementation(({ params: { Body: stream } }) => {
            const done = async () => {
                return new Promise((resolve, reject) => {
                    stream.on('data', (chunk: any) => {
                        uploadedData = Buffer.concat([uploadedData, chunk])
                    })
                    stream.on('error', reject)
                    stream.on('end', () => resolve({ Location: 'https://test-bucket.s3.amazonaws.com/test-key' }))
                })
            }

            mockUploadDone = jest.fn().mockImplementation(done)

            // Mock the 'on' method for progress tracking
            const mockOn = jest.fn()

            return {
                done: mockUploadDone,
                on: mockOn,
            }
        })
        jest.mocked(Upload).mockImplementation(mockUpload)

        processOnSpy = jest.spyOn(process, 'on')
        process.env.POD_NAME = 'test-pod'
    })

    afterEach(() => {
        jest.clearAllMocks()
        uploadedData = Buffer.alloc(0)
        processOnSpy.mockRestore()
        delete process.env.POD_NAME
        process.removeAllListeners('SIGUSR2')
    })

    describe('initializeHeapDump', () => {
        it('should not setup handler when disabled', () => {
            config.HEAP_DUMP_ENABLED = false
            initializeHeapDump(config, s3Client)
            expect(processOnSpy).not.toHaveBeenCalled()
        })

        it('should not setup handler when S3 client is not provided', () => {
            initializeHeapDump(config, undefined)
            expect(processOnSpy).not.toHaveBeenCalled()
        })

        it('should not setup handler when bucket is not configured', () => {
            config.HEAP_DUMP_S3_BUCKET = ''
            initializeHeapDump(config, s3Client)
            expect(processOnSpy).not.toHaveBeenCalled()
        })

        it('should not setup handler when region is not configured', () => {
            config.HEAP_DUMP_S3_REGION = ''
            initializeHeapDump(config, undefined)
            expect(processOnSpy).not.toHaveBeenCalled()
        })

        it('should setup SIGUSR2 signal handler when enabled', () => {
            initializeHeapDump(config, s3Client)
            expect(processOnSpy).toHaveBeenCalledWith('SIGUSR2', expect.any(Function))
        })
    })

    describe('createHeapDump', () => {
        it('should create heap dump and upload to S3', async () => {
            await createHeapDump(s3Client, 'test-heap-dumps', 'heap-dumps')

            expect(mockUpload).toHaveBeenCalledTimes(1)
            expect(mockUpload).toHaveBeenCalledWith(
                expect.objectContaining({
                    client: s3Client,
                    params: expect.objectContaining({
                        Bucket: 'test-heap-dumps',
                        ContentType: 'application/octet-stream',
                        Key: expect.stringMatching(
                            /^heap-dumps\/\d{4}-\d{2}-\d{2}\/heapdump-test-pod-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z\.heapsnapshot$/
                        ),
                        Body: expect.any(Object), // PassThrough stream
                    }),
                })
            )
            expect(mockUploadDone).toHaveBeenCalled()
            expect(uploadedData.length).toBeGreaterThan(0)
        })

        it('should generate unique keys for each dump', async () => {
            await createHeapDump(s3Client, 'test-heap-dumps', 'heap-dumps')
            const firstKey = mockUpload.mock.calls[0][0].params.Key

            // Small delay
            await new Promise((resolve) => setTimeout(resolve, 1))

            await createHeapDump(s3Client, 'test-heap-dumps', 'heap-dumps')
            const secondKey = mockUpload.mock.calls[1][0].params.Key

            expect(firstKey).not.toBe(secondKey)
            expect(firstKey).toMatch(
                /^heap-dumps\/\d{4}-\d{2}-\d{2}\/heapdump-test-pod-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z\.heapsnapshot$/
            )
            expect(secondKey).toMatch(
                /^heap-dumps\/\d{4}-\d{2}-\d{2}\/heapdump-test-pod-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z\.heapsnapshot$/
            )
        })

        it('should handle upload errors', async () => {
            const testError = new Error('Upload failed')

            mockUpload.mockImplementationOnce(() => ({
                done: jest.fn().mockRejectedValue(testError),
                on: jest.fn(), // Mock the 'on' method for progress tracking
            }))

            await expect(createHeapDump(s3Client, 'test-heap-dumps', 'heap-dumps')).rejects.toThrow(testError)
        })
    })
})

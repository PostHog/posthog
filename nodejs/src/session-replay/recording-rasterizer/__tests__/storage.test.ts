import { uploadToS3 } from '../storage'

const mockDone = jest.fn().mockResolvedValue({})
const mockOn = jest.fn()

jest.mock('@aws-sdk/client-s3', () => ({
    S3Client: jest.fn().mockImplementation(() => ({})),
}))

jest.mock('@aws-sdk/lib-storage', () => ({
    Upload: jest.fn().mockImplementation(() => ({
        done: mockDone,
        on: mockOn,
    })),
}))

jest.mock('fs', () => ({
    createReadStream: jest.fn().mockReturnValue('mock-stream'),
}))

const { Upload } = require('@aws-sdk/lib-storage')
const fsModule = require('fs')

describe('uploadToS3', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        mockDone.mockResolvedValue({})
    })

    it('uses the provided id for the S3 key', async () => {
        const key = await uploadToS3('/tmp/video.mp4', 'my-bucket', 'exports/team-1', 'activity-123')
        expect(key).toBe('s3://my-bucket/exports/team-1/activity-123.mp4')
    })

    it('produces different keys for different ids', async () => {
        const key1 = await uploadToS3('/tmp/a.mp4', 'bucket', 'prefix', 'id-aaa')
        const key2 = await uploadToS3('/tmp/b.mp4', 'bucket', 'prefix', 'id-bbb')
        expect(key1).toBe('s3://bucket/prefix/id-aaa.mp4')
        expect(key2).toBe('s3://bucket/prefix/id-bbb.mp4')
    })

    it('produces the same key for the same id (idempotent retries)', async () => {
        const key1 = await uploadToS3('/tmp/a.mp4', 'bucket', 'prefix', 'retry-id')
        const key2 = await uploadToS3('/tmp/a.mp4', 'bucket', 'prefix', 'retry-id')
        expect(key1).toBe(key2)
    })

    it('creates Upload with correct bucket, key, content type, and file stream', async () => {
        await uploadToS3('/tmp/video.mp4', 'my-bucket', 'exports/team-1', 'abc-123')

        expect(fsModule.createReadStream).toHaveBeenCalledWith('/tmp/video.mp4')
        expect(Upload).toHaveBeenCalledWith(
            expect.objectContaining({
                params: {
                    Bucket: 'my-bucket',
                    Key: 'exports/team-1/abc-123.mp4',
                    Body: 'mock-stream',
                    ContentType: 'video/mp4',
                },
            })
        )
    })

    it('uses webm extension and content type for webm format', async () => {
        const key = await uploadToS3('/tmp/video.webm', 'my-bucket', 'exports/team-1', 'abc-123', 'webm')
        expect(key).toBe('s3://my-bucket/exports/team-1/abc-123.webm')

        expect(Upload).toHaveBeenCalledWith(
            expect.objectContaining({
                params: expect.objectContaining({
                    Key: 'exports/team-1/abc-123.webm',
                    ContentType: 'video/webm',
                }),
            })
        )
    })

    it('registers httpUploadProgress listener when onProgress is provided', async () => {
        const onProgress = jest.fn()
        await uploadToS3('/tmp/video.mp4', 'my-bucket', 'exports/team-1', 'abc-123', 'mp4', onProgress)

        expect(mockOn).toHaveBeenCalledWith('httpUploadProgress', expect.any(Function))
    })

    it('does not register httpUploadProgress listener when onProgress is omitted', async () => {
        await uploadToS3('/tmp/video.mp4', 'my-bucket', 'exports/team-1', 'abc-123')

        expect(mockOn).not.toHaveBeenCalled()
    })

    it('propagates upload errors', async () => {
        mockDone.mockRejectedValue(new Error('AccessDenied'))
        await expect(uploadToS3('/tmp/v.mp4', 'bucket', 'prefix', 'id')).rejects.toThrow('AccessDenied')
    })
})

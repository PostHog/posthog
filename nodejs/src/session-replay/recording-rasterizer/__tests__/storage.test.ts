import { uploadToS3 } from '../storage'

const sendMock = jest.fn().mockResolvedValue({})

jest.mock('@aws-sdk/client-s3', () => {
    return {
        S3Client: jest.fn().mockImplementation(() => ({ send: sendMock })),
        PutObjectCommand: jest.fn().mockImplementation((input) => input),
    }
})

jest.mock('fs', () => ({
    createReadStream: jest.fn().mockReturnValue('mock-stream'),
}))

const { PutObjectCommand } = require('@aws-sdk/client-s3')
const fsModule = require('fs')

describe('uploadToS3', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        sendMock.mockResolvedValue({})
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

    it('sends PutObjectCommand with correct bucket, key, content type, and file stream', async () => {
        await uploadToS3('/tmp/video.mp4', 'my-bucket', 'exports/team-1', 'abc-123')

        expect(fsModule.createReadStream).toHaveBeenCalledWith('/tmp/video.mp4')
        expect(PutObjectCommand).toHaveBeenCalledWith({
            Bucket: 'my-bucket',
            Key: 'exports/team-1/abc-123.mp4',
            Body: 'mock-stream',
            ContentType: 'video/mp4',
        })
    })

    it('propagates S3 send errors', async () => {
        sendMock.mockRejectedValue(new Error('AccessDenied'))
        await expect(uploadToS3('/tmp/v.mp4', 'bucket', 'prefix', 'id')).rejects.toThrow('AccessDenied')
    })
})

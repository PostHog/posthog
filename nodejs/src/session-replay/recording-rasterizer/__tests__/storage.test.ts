import { uploadToS3 } from '../storage'

jest.mock('@aws-sdk/client-s3', () => {
    const sendMock = jest.fn().mockResolvedValue({})
    return {
        S3Client: jest.fn().mockImplementation(() => ({ send: sendMock })),
        PutObjectCommand: jest.fn().mockImplementation((input) => input),
    }
})

jest.mock('fs', () => ({
    createReadStream: jest.fn().mockReturnValue('mock-stream'),
}))

describe('uploadToS3', () => {
    it('uses the provided id for the S3 key', async () => {
        const key = await uploadToS3('/tmp/video.mp4', 'my-bucket', 'exports/team-1', 'activity-123')
        expect(key).toBe('exports/team-1/activity-123.mp4')
    })

    it('produces different keys for different ids', async () => {
        const key1 = await uploadToS3('/tmp/a.mp4', 'bucket', 'prefix', 'id-aaa')
        const key2 = await uploadToS3('/tmp/b.mp4', 'bucket', 'prefix', 'id-bbb')
        expect(key1).toBe('prefix/id-aaa.mp4')
        expect(key2).toBe('prefix/id-bbb.mp4')
    })

    it('produces the same key for the same id (idempotent retries)', async () => {
        const key1 = await uploadToS3('/tmp/a.mp4', 'bucket', 'prefix', 'retry-id')
        const key2 = await uploadToS3('/tmp/a.mp4', 'bucket', 'prefix', 'retry-id')
        expect(key1).toBe(key2)
    })
})

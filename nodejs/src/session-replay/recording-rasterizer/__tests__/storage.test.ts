import { uploadToS3 } from '~/session-replay/recording-rasterizer/storage'

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

jest.mock('https-proxy-agent', () => ({
    HttpsProxyAgent: jest.fn().mockImplementation((url) => ({ __proxyAgent: url })),
}))
const { HttpsProxyAgent: HttpsProxyAgentMock } = require('https-proxy-agent')

const mockDefaultProvider = jest.fn().mockImplementation((init) => ({ __credentialsProvider: init }))
jest.mock('@aws-sdk/credential-provider-node', () => ({
    defaultProvider: (init: unknown) => mockDefaultProvider(init),
}))

const ORIGINAL_ENV = process.env

describe('S3 client proxy routing', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.resetModules()
        process.env = { ...ORIGINAL_ENV }
        delete process.env.HTTPS_PROXY
        delete process.env.HTTP_PROXY
        delete process.env.https_proxy
        delete process.env.http_proxy
        delete process.env.RASTERIZER_USE_PROXY
    })

    afterEach(() => {
        process.env = ORIGINAL_ENV
    })

    async function triggerS3Client(): Promise<jest.Mock> {
        let mock!: jest.Mock
        await jest.isolateModulesAsync(async () => {
            // Re-mock against the isolated registry so we capture *this* run's constructor call
            jest.doMock('@aws-sdk/client-s3', () => ({ S3Client: jest.fn().mockImplementation(() => ({})) }))
            jest.doMock('@aws-sdk/lib-storage', () => ({
                Upload: jest.fn().mockImplementation(() => ({ done: jest.fn().mockResolvedValue({}), on: jest.fn() })),
            }))
            jest.doMock('fs', () => ({ createReadStream: jest.fn().mockReturnValue('stream') }))
            jest.doMock('https-proxy-agent', () => ({
                HttpsProxyAgent: HttpsProxyAgentMock,
            }))
            jest.doMock('@aws-sdk/credential-provider-node', () => ({
                defaultProvider: (init: unknown) => mockDefaultProvider(init),
            }))
            const { uploadToS3: fresh } = require('~/session-replay/recording-rasterizer/storage')
            await fresh('/tmp/v.mp4', 'b', 'p', 'i')
            mock = require('@aws-sdk/client-s3').S3Client as jest.Mock
        })
        return mock
    }

    it('does not pass a requestHandler or custom credentials when no proxy env var is set', async () => {
        const s3Client = await triggerS3Client()
        const [config] = s3Client.mock.calls[0]
        expect(config).not.toHaveProperty('requestHandler')
        expect(config).not.toHaveProperty('credentials')
        expect(HttpsProxyAgentMock).not.toHaveBeenCalled()
        expect(mockDefaultProvider).not.toHaveBeenCalled()
    })

    it.each([
        { source: 'HTTPS_PROXY', env: 'HTTPS_PROXY' as const },
        { source: 'HTTP_PROXY fallback', env: 'HTTP_PROXY' as const },
        { source: 'lowercase https_proxy', env: 'https_proxy' as const },
        { source: 'lowercase http_proxy', env: 'http_proxy' as const },
    ])('routes both S3 and STS credential refresh through the proxy when $source is set', async ({ env }) => {
        process.env[env] = 'http://smokescreen.smokescreen.svc.cluster.local:4750'
        const s3Client = await triggerS3Client()
        const [config] = s3Client.mock.calls[0]
        expect(HttpsProxyAgentMock).toHaveBeenCalledWith('http://smokescreen.smokescreen.svc.cluster.local:4750')
        // S3 client requests
        expect(config.requestHandler).toEqual({
            httpsAgent: { __proxyAgent: 'http://smokescreen.smokescreen.svc.cluster.local:4750' },
        })
        // Internal STS / IRSA credential refresh
        expect(mockDefaultProvider).toHaveBeenCalledWith({
            clientConfig: {
                requestHandler: {
                    httpsAgent: { __proxyAgent: 'http://smokescreen.smokescreen.svc.cluster.local:4750' },
                },
            },
        })
        expect(config.credentials).toEqual({
            __credentialsProvider: {
                clientConfig: {
                    requestHandler: {
                        httpsAgent: { __proxyAgent: 'http://smokescreen.smokescreen.svc.cluster.local:4750' },
                    },
                },
            },
        })
    })

    it.each(['false', 'False', 'FALSE', '0', 'no', 'off', ' false '])(
        'RASTERIZER_USE_PROXY=%j keeps both S3 and STS direct even when HTTPS_PROXY is set',
        async (value) => {
            process.env.HTTPS_PROXY = 'http://smokescreen:4750'
            process.env.RASTERIZER_USE_PROXY = value
            const s3Client = await triggerS3Client()
            const [config] = s3Client.mock.calls[0]
            expect(config).not.toHaveProperty('requestHandler')
            expect(config).not.toHaveProperty('credentials')
            expect(HttpsProxyAgentMock).not.toHaveBeenCalled()
            expect(mockDefaultProvider).not.toHaveBeenCalled()
        }
    )

    it.each(['true', '1', 'enabled', 'yes', 'disabled'])(
        'RASTERIZER_USE_PROXY=%j leaves both S3 and STS routed via proxy (only known falsy values disable)',
        async (value) => {
            process.env.HTTPS_PROXY = 'http://smokescreen:4750'
            process.env.RASTERIZER_USE_PROXY = value
            const s3Client = await triggerS3Client()
            const [config] = s3Client.mock.calls[0]
            expect(config.requestHandler).toBeDefined()
            expect(config.credentials).toBeDefined()
            expect(HttpsProxyAgentMock).toHaveBeenCalledWith('http://smokescreen:4750')
            expect(mockDefaultProvider).toHaveBeenCalledTimes(1)
        }
    )
})

import { BlockProxy } from '../capture/block-proxy'
import { RasterizationError } from '../errors'
import { RasterizeRecordingInput } from '../types'

const mockInternalFetch = jest.fn()
jest.mock('../../../utils/request', () => ({
    internalFetch: (...args: any[]) => mockInternalFetch(...args),
}))

function baseInput(overrides: Partial<RasterizeRecordingInput> = {}): RasterizeRecordingInput {
    return {
        session_id: 'test-session-123',
        team_id: 1,
        s3_bucket: 'test-bucket',
        s3_key_prefix: 'exports/mp4/team-1/task-1',
        ...overrides,
    }
}

const testCfg = {
    recordingApiBaseUrl: 'http://localhost:6738',
    recordingApiSecret: 'test-secret',
}

const mockLog = {
    info: jest.fn(),
    warn: jest.fn(),
    error: jest.fn(),
    debug: jest.fn(),
    child: jest.fn().mockReturnThis(),
} as any

describe('BlockProxy', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        mockInternalFetch.mockReset()
    })

    describe('fetchBlocks', () => {
        it('returns parsed block count on success', async () => {
            const blocks = [
                { key: 'recordings/block-0', start_byte: 0, end_byte: 1000 },
                { key: 'recordings/block-1', start_byte: 0, end_byte: 2000 },
            ]

            mockInternalFetch.mockResolvedValue({
                status: 200,
                json: jest.fn().mockResolvedValue({ blocks }),
            })

            const proxy = new BlockProxy(testCfg, mockLog)
            const count = await proxy.fetchBlocks(baseInput())

            expect(count).toBe(2)
            expect(proxy.blockCount).toBe(2)
            expect(mockInternalFetch).toHaveBeenCalledWith(
                'http://localhost:6738/api/projects/1/recordings/test-session-123/blocks',
                { headers: { 'X-Internal-Api-Secret': 'test-secret' } }
            )
        })

        it('throws RasterizationError on non-ok response', async () => {
            mockInternalFetch.mockResolvedValue({
                status: 404,
                text: jest.fn().mockResolvedValue('session not found'),
            })

            const proxy = new BlockProxy(testCfg, mockLog)
            await expect(proxy.fetchBlocks(baseInput())).rejects.toThrow(RasterizationError)
            await expect(proxy.fetchBlocks(baseInput())).rejects.toThrow('Failed to fetch block listing: 404')
        })

        it.each([
            [500, true],
            [403, false],
        ])('marks %i response as retryable=%s', async (status, expectedRetryable) => {
            mockInternalFetch.mockResolvedValue({
                status,
                text: jest.fn().mockResolvedValue('error body'),
            })

            const proxy = new BlockProxy(testCfg, mockLog)
            await expect(proxy.fetchBlocks(baseInput())).rejects.toMatchObject({
                retryable: expectedRetryable,
                code: 'BLOCK_LISTING_FAILED',
            })
        })

        it('throws on invalid blocks response', async () => {
            mockInternalFetch.mockResolvedValue({
                status: 200,
                json: jest.fn().mockResolvedValue({ blocks: 'not-an-array' }),
            })

            const proxy = new BlockProxy(testCfg, mockLog)
            await expect(proxy.fetchBlocks(baseInput())).rejects.toThrow('Invalid block listing response')
        })
    })

    describe('handleRequest', () => {
        const blocks = [
            { key: 'recordings/block-0', start_byte: 0, end_byte: 1000 },
            { key: 'recordings/block-1', start_byte: 100, end_byte: 2000 },
        ]

        function mockBlockRequest(path: string) {
            return {
                url: () => `http://localhost:8000${path}`,
                respond: jest.fn().mockResolvedValue(undefined),
                continue: jest.fn(),
            }
        }

        async function createProxyWithBlocks(): Promise<BlockProxy> {
            mockInternalFetch.mockResolvedValueOnce({
                status: 200,
                json: jest.fn().mockResolvedValue({ blocks }),
            })
            const proxy = new BlockProxy(testCfg, mockLog)
            await proxy.fetchBlocks(baseInput())
            mockInternalFetch.mockReset()
            return proxy
        }

        it('proxies valid block index to recording-api with auth header', async () => {
            const proxy = await createProxyWithBlocks()

            mockInternalFetch.mockResolvedValue({
                status: 200,
                headers: { 'content-type': 'application/jsonl' },
                text: jest.fn().mockResolvedValue('{"data":"test"}'),
            })

            const blockRequest = mockBlockRequest('/__blocks/0')
            await proxy.handleRequest(blockRequest as any, '/__blocks/0')

            expect(mockInternalFetch).toHaveBeenCalledWith(
                expect.stringContaining('/api/projects/1/recordings/test-session-123/block?'),
                { headers: { 'X-Internal-Api-Secret': 'test-secret' } }
            )
            const fetchUrl = mockInternalFetch.mock.calls[0][0] as string
            expect(fetchUrl).toContain('key=recordings%2Fblock-0')
            expect(fetchUrl).toContain('start_byte=0')
            expect(fetchUrl).toContain('end_byte=1000')
            expect(fetchUrl).toContain('decompress=true')
            expect(blockRequest.respond).toHaveBeenCalledWith(
                expect.objectContaining({ status: 200, contentType: 'application/jsonl' })
            )
        })

        it('returns 404 for out-of-range index', async () => {
            const proxy = await createProxyWithBlocks()
            const blockRequest = mockBlockRequest('/__blocks/5')
            await proxy.handleRequest(blockRequest as any, '/__blocks/5')

            expect(blockRequest.respond).toHaveBeenCalledWith({ status: 404, body: 'block not found' })
        })

        it('returns 404 for NaN index', async () => {
            const proxy = await createProxyWithBlocks()
            const blockRequest = mockBlockRequest('/__blocks/abc')
            await proxy.handleRequest(blockRequest as any, '/__blocks/abc')

            expect(blockRequest.respond).toHaveBeenCalledWith({ status: 404, body: 'block not found' })
        })

        it('forwards upstream non-ok status', async () => {
            const proxy = await createProxyWithBlocks()

            mockInternalFetch.mockResolvedValue({
                status: 500,
                text: jest.fn().mockResolvedValue('internal error'),
            })
            const blockRequest = mockBlockRequest('/__blocks/0')
            await proxy.handleRequest(blockRequest as any, '/__blocks/0')

            expect(blockRequest.respond).toHaveBeenCalledWith({ status: 500, body: 'internal error' })
        })

        it('returns 502 when upstream fetch throws', async () => {
            const proxy = await createProxyWithBlocks()

            mockInternalFetch.mockRejectedValue(new Error('network timeout'))
            const blockRequest = mockBlockRequest('/__blocks/0')
            await proxy.handleRequest(blockRequest as any, '/__blocks/0')

            expect(blockRequest.respond).toHaveBeenCalledWith({ status: 502, body: 'block proxy error' })
        })
    })
})

import { createServer } from 'http'
import { AddressInfo } from 'net'

import { defaultConfig } from '../../config/config'
import {
    HogFunctionInvocation,
    HogFunctionQueueParametersFetchRequest,
    HogFunctionQueueParametersFetchResponse,
} from '../types'
import { FetchExecutorService } from './fetch-executor.service'

jest.unmock('node-fetch')

describe('FetchExecutorService', () => {
    jest.setTimeout(1000)
    let server: any
    let baseUrl: string
    let service: FetchExecutorService
    let mockRequest = jest.fn()

    beforeAll(() => {
        server = createServer((req, res) => {
            mockRequest(req, res)
        })

        server.listen(0) // Random available port
        const address = server.address() as AddressInfo
        baseUrl = `http://localhost:${address.port}`
        service = new FetchExecutorService(defaultConfig)
    })

    afterAll((done) => {
        server.close(done)
    })

    beforeEach(() => {
        mockRequest = jest.fn((req, res) => {
            res.writeHead(200, { 'Content-Type': 'text/plain' })
            res.end('Hello, world!')
        })
    })

    const createInvocation = (params: HogFunctionQueueParametersFetchRequest): HogFunctionInvocation => ({
        id: 'test-id',
        globals: {} as any,
        teamId: 1,
        hogFunction: {} as any,
        queue: 'fetch',
        queueParameters: params,
        queuePriority: 0,
        timings: [],
    })

    it('completes successful fetch', async () => {
        const invocation = createInvocation({
            url: `${baseUrl}/test`,
            method: 'GET',
            return_queue: 'hog',
        })

        const result = await service.execute(invocation)

        expect(mockRequest).toHaveBeenCalledWith(
            expect.objectContaining({
                method: 'GET',
                url: '/test',
            }),
            expect.any(Object)
        )
        const params = result.invocation.queueParameters as HogFunctionQueueParametersFetchResponse

        expect(result.invocation.queue).toBe('hog')
        expect(params.response).toEqual({
            status: 200,
            headers: expect.objectContaining({ 'content-type': 'text/plain' }),
        })
        expect(params.body).toBe('Hello, world!')
    })

    it('handles failure status and retries', async () => {
        let attempts = 0

        mockRequest.mockImplementation((req: any, res: any) => {
            attempts++
            res.writeHead(500, { 'Content-Type': 'text/plain' })
            res.end('test server error body')
        })

        const invocation = createInvocation({
            url: `${baseUrl}/test`,
            method: 'GET',
            return_queue: 'hog',
            max_tries: 2,
        })

        const result = await service.execute(invocation)

        // Should be scheduled for retry
        expect(result.invocation.queue).toBe('fetch')
        expect(result.invocation.queueMetadata?.tries).toBe(1)
        expect(result.invocation.queueMetadata?.trace[0]).toEqual(
            expect.objectContaining({
                kind: 'failurestatus',
                status: 500,
                message: 'Received failure status: 500',
            })
        )
        expect(result.invocation.queuePriority).toBe(1) // Priority decreased
        expect(result.invocation.queueScheduledAt).toBeDefined()

        // Execute the retry
        const retryResult = await service.execute(result.invocation)
        const params = retryResult.invocation.queueParameters as HogFunctionQueueParametersFetchResponse

        // Should now be complete with failure
        expect(retryResult.invocation.queue).toBe('hog')
        expect(params.trace?.length).toBe(2)
        expect(params.response).toBeNull()
        expect(attempts).toBe(2)
    })

    it('handles request errors', async () => {
        const invocation = createInvocation({
            url: 'http://non-existent-host-name',
            method: 'GET',
            return_queue: 'hog',
        })

        const result = await service.execute(invocation)

        // Should be scheduled for retry
        expect(result.invocation.queue).toBe('fetch')
        expect(result.invocation.queueMetadata?.tries).toBe(1)
        expect(result.invocation.queueMetadata?.trace[0]).toEqual(
            expect.objectContaining({
                kind: 'requesterror',
            })
        )
    })

    it('handles timeouts', async () => {
        mockRequest.mockImplementation((_req: any, res: any) => {
            // Never send response
            setTimeout(() => res.end(), 10000)
        })

        const invocation = createInvocation({
            url: `${baseUrl}/test`,
            method: 'GET',
            return_queue: 'hog',
        })

        // Set a very short timeout
        const timeoutService = new FetchExecutorService({
            ...defaultConfig,
            CDP_FETCH_TIMEOUT_MS: 100,
        })

        const result = await timeoutService.execute(invocation)

        expect(result.invocation.queue).toBe('fetch')
        expect(result.invocation.queueMetadata?.trace[0]).toEqual(
            expect.objectContaining({
                kind: 'timeout',
            })
        )
    })

    it('completes fetch with headers', async () => {
        mockRequest.mockImplementation((req: any, res: any) => {
            expect(req.headers['x-test']).toBe('test')
            res.writeHead(200)
            res.end('Hello, world!')
        })

        const invocation = createInvocation({
            url: `${baseUrl}/test`,
            method: 'GET',
            headers: {
                'X-Test': 'test',
            },
            return_queue: 'hog',
        })

        const result = await service.execute(invocation)
        const params = result.invocation.queueParameters as HogFunctionQueueParametersFetchResponse

        expect(result.invocation.queue).toBe('hog')
        expect(params.response?.status).toBe(200)
    })

    it('completes fetch with body', async () => {
        mockRequest.mockImplementation((req: any, res: any) => {
            let body = ''
            req.on('data', (chunk: any) => {
                body += chunk
            })
            req.on('end', () => {
                expect(body).toBe('test body')
                res.writeHead(200)
                res.end('Hello, world!')
            })
        })

        const invocation = createInvocation({
            url: `${baseUrl}/test`,
            method: 'POST',
            body: 'test body',
            return_queue: 'hog',
        })

        const result = await service.execute(invocation)
        const params = result.invocation.queueParameters as HogFunctionQueueParametersFetchResponse

        expect(result.invocation.queue).toBe('hog')
        expect(params.response?.status).toBe(200)
    })

    it('handles minimum parameters', async () => {
        mockRequest.mockImplementation((req: any, res: any) => {
            expect(req.method).toBe('GET')
            res.writeHead(200)
            res.end('Hello, world!')
        })

        const invocation = createInvocation({
            url: `${baseUrl}/test`,
            method: 'GET',
            return_queue: 'hog',
        })

        const result = await service.execute(invocation)
        const params = result.invocation.queueParameters as HogFunctionQueueParametersFetchResponse

        expect(result.invocation.queue).toBe('hog')
        expect(params.response?.status).toBe(200)
    })
})

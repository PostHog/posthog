import { Request, Response } from 'ultimate-express'

import { createInternalApiAuthMiddleware } from './internal-api-auth'

describe('createInternalApiAuthMiddleware', () => {
    const mockResponse = () => {
        const res = {} as Response
        res.status = jest.fn().mockReturnValue(res)
        res.json = jest.fn().mockReturnValue(res)
        return res
    }

    const mockRequest = (path: string, headers: Record<string, string> = {}) => {
        return {
            headers,
            path,
            method: 'GET',
        } as unknown as Request
    }

    describe('when no secret configured', () => {
        it.each([
            ['no secret configured', ''],
            ['empty secret configured', ''],
        ])('should allow request when %s', (_, configuredSecret) => {
            const middleware = createInternalApiAuthMiddleware({ secret: configuredSecret })
            const req = mockRequest('/api/test')
            const res = mockResponse()
            const next = jest.fn()

            middleware(req, res, next)

            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })
    })

    describe('when secret configured', () => {
        it('should reject request when header is missing', () => {
            const middleware = createInternalApiAuthMiddleware({ secret: 'test-secret' })
            const req = mockRequest('/api/test', {})
            const res = mockResponse()
            const next = jest.fn()

            middleware(req, res, next)

            expect(next).not.toHaveBeenCalled()
            expect(res.status).toHaveBeenCalledWith(401)
            expect(res.json).toHaveBeenCalledWith({ error: 'Unauthorized: Missing authentication header' })
        })

        it('should reject request when secret does not match', () => {
            const middleware = createInternalApiAuthMiddleware({ secret: 'correct-secret' })
            const req = mockRequest('/api/test', { 'x-internal-api-secret': 'wrong-secret' })
            const res = mockResponse()
            const next = jest.fn()

            middleware(req, res, next)

            expect(next).not.toHaveBeenCalled()
            expect(res.status).toHaveBeenCalledWith(401)
            expect(res.json).toHaveBeenCalledWith({ error: 'Unauthorized: Invalid authentication' })
        })

        it.each([['x-internal-api-secret'], ['X-Internal-Api-Secret'], ['X-INTERNAL-API-SECRET']])(
            'should allow request when secret matches with %s header',
            (headerName) => {
                const middleware = createInternalApiAuthMiddleware({ secret: 'correct-secret' })
                const req = mockRequest('/api/test', { [headerName]: 'correct-secret' })
                const res = mockResponse()
                const next = jest.fn()

                middleware(req, res, next)

                expect(next).toHaveBeenCalled()
                expect(res.status).not.toHaveBeenCalled()
            }
        )

        it('should reject when secrets have different lengths', () => {
            const middleware = createInternalApiAuthMiddleware({ secret: 'short' })
            const req = mockRequest('/api/test', { 'x-internal-api-secret': 'much-longer-secret' })
            const res = mockResponse()
            const next = jest.fn()

            middleware(req, res, next)

            expect(next).not.toHaveBeenCalled()
            expect(res.status).toHaveBeenCalledWith(401)
        })

        it('should reject when header value is not a string', () => {
            const middleware = createInternalApiAuthMiddleware({ secret: 'test-secret' })
            const req = {
                headers: { 'x-internal-api-secret': ['array', 'of', 'values'] },
                path: '/api/test',
                method: 'GET',
            } as unknown as Request
            const res = mockResponse()
            const next = jest.fn()

            middleware(req, res, next)

            expect(next).not.toHaveBeenCalled()
            expect(res.status).toHaveBeenCalledWith(401)
            expect(res.json).toHaveBeenCalledWith({ error: 'Unauthorized: Missing authentication header' })
        })
    })

    describe('path exclusions', () => {
        it.each([
            ['/public/webhooks/123', 'public path'],
            ['/_health', 'health check'],
            ['/_ready', 'ready check'],
            ['/_metrics', 'metrics'],
            ['/metrics', 'prometheus metrics'],
        ])('should skip auth for %s (%s)', (path) => {
            const middleware = createInternalApiAuthMiddleware({ secret: 'test-secret' })
            const req = mockRequest(path, {})
            const res = mockResponse()
            const next = jest.fn()

            middleware(req, res, next)

            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })

        it('should allow custom excluded path prefixes', () => {
            const middleware = createInternalApiAuthMiddleware({
                secret: 'test-secret',
                excludedPathPrefixes: ['/custom/'],
            })
            const req = mockRequest('/custom/endpoint', {})
            const res = mockResponse()
            const next = jest.fn()

            middleware(req, res, next)

            expect(next).toHaveBeenCalled()
            expect(res.status).not.toHaveBeenCalled()
        })

        it('should still require auth for non-excluded paths', () => {
            const middleware = createInternalApiAuthMiddleware({ secret: 'test-secret' })
            const req = mockRequest('/api/some/endpoint', {})
            const res = mockResponse()
            const next = jest.fn()

            middleware(req, res, next)

            expect(next).not.toHaveBeenCalled()
            expect(res.status).toHaveBeenCalledWith(401)
        })
    })
})

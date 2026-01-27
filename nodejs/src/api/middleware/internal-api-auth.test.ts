import { Request, Response } from 'ultimate-express'

import { createInternalApiAuthMiddleware } from './internal-api-auth'

describe('createInternalApiAuthMiddleware', () => {
    const mockResponse = () => {
        const res = {} as Response
        res.status = jest.fn().mockReturnValue(res)
        res.json = jest.fn().mockReturnValue(res)
        return res
    }

    const mockRequest = (headers: Record<string, string> = {}) => {
        return {
            headers,
            path: '/api/test',
            method: 'GET',
        } as unknown as Request
    }

    it.each([
        ['no secret configured', '', undefined],
        ['empty secret configured', '', ''],
    ])('should allow request when %s', (_, configuredSecret, providedHeader) => {
        const middleware = createInternalApiAuthMiddleware(configuredSecret)
        const req = mockRequest(providedHeader ? { 'x-internal-api-secret': providedHeader } : {})
        const res = mockResponse()
        const next = jest.fn()

        middleware(req, res, next)

        expect(next).toHaveBeenCalled()
        expect(res.status).not.toHaveBeenCalled()
    })

    it('should reject request when secret is configured but header is missing', () => {
        const middleware = createInternalApiAuthMiddleware('test-secret')
        const req = mockRequest({})
        const res = mockResponse()
        const next = jest.fn()

        middleware(req, res, next)

        expect(next).not.toHaveBeenCalled()
        expect(res.status).toHaveBeenCalledWith(401)
        expect(res.json).toHaveBeenCalledWith({ error: 'Unauthorized: Missing authentication header' })
    })

    it('should reject request when secret does not match', () => {
        const middleware = createInternalApiAuthMiddleware('correct-secret')
        const req = mockRequest({ 'x-internal-api-secret': 'wrong-secret' })
        const res = mockResponse()
        const next = jest.fn()

        middleware(req, res, next)

        expect(next).not.toHaveBeenCalled()
        expect(res.status).toHaveBeenCalledWith(401)
        expect(res.json).toHaveBeenCalledWith({ error: 'Unauthorized: Invalid authentication' })
    })

    it('should allow request when secret matches', () => {
        const middleware = createInternalApiAuthMiddleware('correct-secret')
        const req = mockRequest({ 'x-internal-api-secret': 'correct-secret' })
        const res = mockResponse()
        const next = jest.fn()

        middleware(req, res, next)

        expect(next).toHaveBeenCalled()
        expect(res.status).not.toHaveBeenCalled()
    })

    it('should reject when secrets have different lengths', () => {
        const middleware = createInternalApiAuthMiddleware('short')
        const req = mockRequest({ 'x-internal-api-secret': 'much-longer-secret' })
        const res = mockResponse()
        const next = jest.fn()

        middleware(req, res, next)

        expect(next).not.toHaveBeenCalled()
        expect(res.status).toHaveBeenCalledWith(401)
    })

    it('should reject when header value is not a string', () => {
        const middleware = createInternalApiAuthMiddleware('test-secret')
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

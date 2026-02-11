import type { PluginsServerConfig } from '../types'
import { getInternalApiHeaders, internalDjangoRequest } from './internal-django-client'

describe('internal-django-client', () => {
    const mockConfig = {
        INTERNAL_API_SECRET: 'test-secret-123',
    } as Pick<PluginsServerConfig, 'INTERNAL_API_SECRET'>

    beforeEach(() => {
        jest.clearAllMocks()
    })

    describe('getInternalApiHeaders', () => {
        it('includes secret when configured', () => {
            const headers = getInternalApiHeaders(mockConfig)
            expect(headers).toEqual({
                'X-Internal-Api-Secret': 'test-secret-123',
            })
        })

        it('returns empty object when no secret configured', () => {
            const headers = getInternalApiHeaders({ INTERNAL_API_SECRET: '' })
            expect(headers).toEqual({})
        })
    })

    describe('internalDjangoRequest', () => {
        beforeEach(() => {
            // Mock the internalFetch function
            jest.mock('./request', () => ({
                internalFetch: jest.fn(),
            }))
        })

        it('adds authentication header when secret is configured', async () => {
            const { internalFetch } = require('./request')
            const mockResponse = {
                status: 200,
                headers: {},
                json: jest.fn().mockResolvedValue({ data: 'test' }),
                text: jest.fn().mockResolvedValue('test'),
                dump: jest.fn(),
            }
            internalFetch.mockResolvedValue(mockResponse)

            await internalDjangoRequest(mockConfig, 'https://api.example.com/internal/endpoint', {
                method: 'GET',
            })

            expect(internalFetch).toHaveBeenCalledWith('https://api.example.com/internal/endpoint', {
                method: 'GET',
                headers: {
                    'X-Internal-Api-Secret': 'test-secret-123',
                },
            })
        })

        it('merges custom headers with authentication header', async () => {
            const { internalFetch } = require('./request')
            const mockResponse = {
                status: 200,
                headers: {},
                json: jest.fn().mockResolvedValue({ data: 'test' }),
                text: jest.fn().mockResolvedValue('test'),
                dump: jest.fn(),
            }
            internalFetch.mockResolvedValue(mockResponse)

            await internalDjangoRequest(mockConfig, 'https://api.example.com/internal/endpoint', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Custom-Header': 'value',
                },
            })

            expect(internalFetch).toHaveBeenCalledWith('https://api.example.com/internal/endpoint', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Custom-Header': 'value',
                    'X-Internal-Api-Secret': 'test-secret-123',
                },
            })
        })

        it('does not add header when secret is not configured', async () => {
            const { internalFetch } = require('./request')
            const mockResponse = {
                status: 200,
                headers: {},
                json: jest.fn().mockResolvedValue({ data: 'test' }),
                text: jest.fn().mockResolvedValue('test'),
                dump: jest.fn(),
            }
            internalFetch.mockResolvedValue(mockResponse)

            await internalDjangoRequest({ INTERNAL_API_SECRET: '' }, 'https://api.example.com/internal/endpoint', {
                method: 'GET',
            })

            expect(internalFetch).toHaveBeenCalledWith('https://api.example.com/internal/endpoint', {
                method: 'GET',
                headers: {},
            })
        })

        it('passes through all fetch options', async () => {
            const { internalFetch } = require('./request')
            const mockResponse = {
                status: 200,
                headers: {},
                json: jest.fn().mockResolvedValue({ data: 'test' }),
                text: jest.fn().mockResolvedValue('test'),
                dump: jest.fn(),
            }
            internalFetch.mockResolvedValue(mockResponse)

            const body = JSON.stringify({ test: 'data' })
            await internalDjangoRequest(mockConfig, 'https://api.example.com/internal/endpoint', {
                method: 'POST',
                body,
                timeoutMs: 5000,
            })

            expect(internalFetch).toHaveBeenCalledWith('https://api.example.com/internal/endpoint', {
                method: 'POST',
                body,
                timeoutMs: 5000,
                headers: {
                    'X-Internal-Api-Secret': 'test-secret-123',
                },
            })
        })
    })
})

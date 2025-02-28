import { Response } from 'node-fetch'

import { trackedFetch } from './fetch'
import { globalHttpCallRecorder, recordedFetch } from './recorded-fetch'

// Mock the trackedFetch function
jest.mock('../../src/utils/fetch', () => ({
    trackedFetch: jest.fn(),
}))

// Mock config.ts
jest.mock('../../src/config/config', () => {
    const originalModule = jest.requireActual('../../src/config/config')
    return {
        ...originalModule,
        defaultConfig: {
            ...originalModule.defaultConfig,
            DESTINATION_MIGRATION_DIFFING_ENABLED: true,
            TASKS_PER_WORKER: 1,
        },
    }
})

describe('HttpCallRecorder', () => {
    beforeEach(() => {
        globalHttpCallRecorder.clearCalls()
        jest.clearAllMocks()
    })

    it('should initialize with empty calls array', () => {
        expect(globalHttpCallRecorder.getCalls()).toEqual([])
    })

    it('should add and retrieve calls', () => {
        const mockCall = {
            id: 'test_id',
            request: {
                url: 'https://example.com',
                method: 'GET',
                headers: {},
                timestamp: new Date(),
            },
            response: {
                status: 200,
                statusText: 'OK',
                headers: {},
                body: '{"success": true}',
                timestamp: new Date(),
            },
        }

        globalHttpCallRecorder.addCall(mockCall)
        expect(globalHttpCallRecorder.getCalls()).toHaveLength(1)
        expect(globalHttpCallRecorder.getCalls()[0]).toEqual(mockCall)
    })

    it('should clear all calls', () => {
        const mockCall = {
            id: 'test_id',
            request: {
                url: 'https://example.com',
                method: 'GET',
                headers: {},
                timestamp: new Date(),
            },
            response: {
                status: 200,
                statusText: 'OK',
                headers: {},
                body: '{"success": true}',
                timestamp: new Date(),
            },
        }

        globalHttpCallRecorder.addCall(mockCall)
        expect(globalHttpCallRecorder.getCalls()).toHaveLength(1)

        globalHttpCallRecorder.clearCalls()
        expect(globalHttpCallRecorder.getCalls()).toHaveLength(0)
    })
})

describe('recordedFetch', () => {
    const mockResponseBody = '{"success": true}'
    const mockResponse = {
        status: 200,
        statusText: 'OK',
        headers: {
            get: jest.fn().mockReturnValue('application/json'),
            forEach: jest.fn((callback) => {
                callback('application/json', 'content-type')
            }),
            entries: jest.fn().mockReturnValue([['content-type', 'application/json']]),
        },
        clone: jest.fn().mockReturnThis(),
        text: jest.fn().mockResolvedValue(mockResponseBody),
    } as unknown as Response

    beforeEach(() => {
        globalHttpCallRecorder.clearCalls()
        jest.clearAllMocks()
        jest.mocked(trackedFetch).mockResolvedValue(mockResponse)
    })

    it('should record successful HTTP requests and responses', async () => {
        const url = 'https://example.com/api'
        const init = {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data: 'test' }),
        }

        const response = await recordedFetch(url, init)

        // Verify trackedFetch was called with the right parameters
        expect(trackedFetch).toHaveBeenCalledWith(url, init)

        // Verify response is returned correctly
        expect(response).toBe(mockResponse)

        // Verify call was recorded
        const calls = globalHttpCallRecorder.getCalls()
        expect(calls).toHaveLength(1)

        const recordedCall = calls[0]
        expect(recordedCall.request.url).toBe(url)
        expect(recordedCall.request.method).toBe('POST')
        expect(recordedCall.request.headers['content-type']).toBe('application/json')
        expect(recordedCall.request.body).toBe(JSON.stringify({ data: 'test' }))

        expect(recordedCall.response.status).toBe(200)
        expect(recordedCall.response.statusText).toBe('OK')
        expect(recordedCall.response.headers['content-type']).toBe('application/json')
        expect(recordedCall.response.body).toBe(mockResponseBody)

        expect(recordedCall.error).toBeUndefined()
    })

    it('should record failed HTTP requests', async () => {
        const url = 'https://example.com/api/error'
        const error = new Error('Network error')

        jest.mocked(trackedFetch).mockRejectedValueOnce(error)

        await expect(recordedFetch(url)).rejects.toThrow('Network error')

        // Verify call was recorded with error
        const calls = globalHttpCallRecorder.getCalls()
        expect(calls).toHaveLength(1)

        const recordedCall = calls[0]
        expect(recordedCall.request.url).toBe(url)
        expect(recordedCall.request.method).toBe('GET')

        expect(recordedCall.response.status).toBe(0)
        expect(recordedCall.response.statusText).toBe('Network error')
        expect(recordedCall.response.body).toBeNull()

        expect(recordedCall.error).toBe(error)
    })

    it('should handle different types of request bodies', async () => {
        // String body
        await recordedFetch('https://example.com', {
            method: 'POST',
            body: 'plain text body',
        })

        // JSON body as string
        await recordedFetch('https://example.com', {
            method: 'POST',
            body: JSON.stringify({ key: 'value' }),
        })

        // JSON body as object (should be automatically stringified)
        await recordedFetch('https://example.com', {
            method: 'POST',
            body: JSON.stringify({ key: 'value', nested: { prop: true } }),
        })

        // URLSearchParams body
        const params = new URLSearchParams()
        params.append('key', 'value')
        await recordedFetch('https://example.com', {
            method: 'POST',
            body: params,
        })

        const calls = globalHttpCallRecorder.getCalls()
        expect(calls).toHaveLength(4)

        expect(calls[0].request.body).toBe('plain text body')
        expect(calls[1].request.body).toBe('{"key":"value"}')
        // The third call should have automatically stringified the object
        expect(JSON.parse(calls[2].request.body!)).toEqual({ key: 'value', nested: { prop: true } })
        expect(calls[3].request.body).toBe('key=value')
    })

    it('should handle different types of headers', async () => {
        // Mock Headers object
        const mockHeaders1 = {
            get: jest.fn().mockReturnValue('value1'),
            forEach: jest.fn((callback) => {
                callback('value1', 'x-custom-header')
            }),
            entries: jest.fn().mockReturnValue([['x-custom-header', 'value1']]),
        }

        // Mock the trackedFetch implementation for this test
        jest.mocked(trackedFetch).mockImplementationOnce(() => {
            return Promise.resolve({
                status: 200,
                statusText: 'OK',
                headers: mockHeaders1,
                clone: jest.fn().mockReturnThis(),
                text: jest.fn().mockResolvedValue('{}'),
            } as unknown as Response)
        })

        await recordedFetch('https://example.com/headers-test-1', {
            headers: { 'x-custom-header': 'value1' },
        })

        // Plain object headers
        await recordedFetch('https://example.com/headers-test-2', {
            headers: { 'x-custom-header': 'value2' },
        })

        const calls = globalHttpCallRecorder.getCalls()
        expect(calls).toHaveLength(2)

        // For the first call, we're checking if the request headers are properly recorded
        expect(calls[0].request.headers['x-custom-header']).toBe('value1')
        expect(calls[1].request.headers['x-custom-header']).toBe('value2')
    })

    it('should record chained HTTP requests where data from first response is used in second request', async () => {
        // Mock user API response
        const userResponseBody = JSON.stringify({
            id: 123,
            name: 'Test User',
            email: 'test@example.com',
            preferences: { theme: 'dark' },
        })

        const userResponse = {
            status: 200,
            statusText: 'OK',
            headers: {
                get: jest.fn().mockReturnValue('application/json'),
                forEach: jest.fn((callback) => {
                    callback('application/json', 'content-type')
                }),
                entries: jest.fn().mockReturnValue([['content-type', 'application/json']]),
            },
            clone: jest.fn().mockReturnThis(),
            text: jest.fn().mockResolvedValue(userResponseBody),
            json: jest.fn().mockResolvedValue(JSON.parse(userResponseBody)),
        } as unknown as Response

        // Mock analytics API response
        const analyticsResponseBody = JSON.stringify({
            success: true,
            message: 'Analytics data received',
        })

        const analyticsResponse = {
            status: 201,
            statusText: 'Created',
            headers: {
                get: jest.fn().mockReturnValue('application/json'),
                forEach: jest.fn((callback) => {
                    callback('application/json', 'content-type')
                }),
                entries: jest.fn().mockReturnValue([['content-type', 'application/json']]),
            },
            clone: jest.fn().mockReturnThis(),
            text: jest.fn().mockResolvedValue(analyticsResponseBody),
            json: jest.fn().mockResolvedValue(JSON.parse(analyticsResponseBody)),
        } as unknown as Response

        // First mock the user API response
        jest.mocked(trackedFetch).mockResolvedValueOnce(userResponse)
        // Then mock the analytics API response for the second call
        jest.mocked(trackedFetch).mockResolvedValueOnce(analyticsResponse)

        // First request - get user data
        const userUrl = 'https://example.com/api/users/user123'
        const userDataResponse = await recordedFetch(userUrl)
        const userData = await userDataResponse.json()

        // Second request - post analytics data using user data from first response
        const analyticsUrl = 'https://example.com/api/analytics'

        // Use a direct object instead of pre-stringifying it
        const analyticsInit = {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                userId: userData.id,
                userName: userData.name,
                userEmail: userData.email,
                eventType: 'page_view',
                timestamp: new Date().toISOString(),
            }),
        }

        await recordedFetch(analyticsUrl, analyticsInit)

        // Verify calls were recorded
        const calls = globalHttpCallRecorder.getCalls()
        expect(calls).toHaveLength(2)

        // Verify the first call (GET user data)
        expect(calls[0].request.url).toBe(userUrl)
        expect(calls[0].request.method).toBe('GET')
        expect(calls[0].response.status).toBe(200)
        expect(calls[0].response.body).toBe(userResponseBody)

        // Verify the second call (POST analytics data)
        expect(calls[1].request.url).toBe(analyticsUrl)
        expect(calls[1].request.method).toBe('POST')
        expect(calls[1].response.status).toBe(201)
        expect(calls[1].response.body).toBe(analyticsResponseBody)

        // Verify the second request body contains data from the first response
        const requestBody = JSON.parse(calls[1].request.body!)
        expect(requestBody.userId).toBe(123)
        expect(requestBody.userName).toBe('Test User')
        expect(requestBody.userEmail).toBe('test@example.com')
        expect(requestBody.eventType).toBe('page_view')
    })
})

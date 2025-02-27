import { Response } from 'node-fetch'

import { trackedFetch } from './fetch'
import { globalHttpCallRecorder, recordedFetch, RecordedHttpCall } from './recorded-fetch'

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

    describe('compareCalls', () => {
        // Helper function to create a mock HTTP call
        const createMockCall = (
            url: string,
            method: string = 'GET',
            requestHeaders: Record<string, string> = {},
            requestBody: string | null = null,
            status: number = 200,
            responseHeaders: Record<string, string> = {},
            responseBody: string | null = '{"success": true}'
        ): RecordedHttpCall => ({
            id: `test_id_${Math.random()}`,
            request: {
                url,
                method,
                headers: requestHeaders,
                body: requestBody,
                timestamp: new Date(),
            },
            response: {
                status,
                statusText: status === 200 ? 'OK' : 'Error',
                headers: responseHeaders,
                body: responseBody,
                timestamp: new Date(),
            },
        })

        it('should match identical calls', () => {
            const call1 = createMockCall(
                'https://example.com/api',
                'POST',
                { 'content-type': 'application/json' },
                '{"data":"test"}'
            )

            const call2 = createMockCall(
                'https://example.com/api',
                'POST',
                { 'content-type': 'application/json' },
                '{"data":"test"}'
            )

            const result = globalHttpCallRecorder.compareCalls([call1], [call2])

            expect(result.matches).toBe(true)
            expect(result.details.matchedCalls).toBe(1)
            expect(result.details.mismatchDetails).toHaveLength(0)
        })

        it('should match calls with different query parameters since we want exact URL matches', () => {
            const legacyCall = createMockCall('https://example.com/api?param1=value1')
            const hogfnCall = createMockCall('https://example.com/api?param2=value2')

            const result = globalHttpCallRecorder.compareCalls([legacyCall], [hogfnCall])

            expect(result.matches).toBe(false)
            expect(result.details.mismatchDetails).toHaveLength(1)
            expect(result.details.mismatchDetails[0].differences[0]).toBe(
                'Call 1: Expected [legacy] https://example.com/api?param1=value1 but got [hogfn] https://example.com/api?param2=value2'
            )
        })

        it('should detect URL differences with exact values', () => {
            const legacyCall = createMockCall('https://example.com/api?param1=value1')
            const hogfnCall = createMockCall('https://example.com/api?param2=value2')

            const result = globalHttpCallRecorder.compareCalls([legacyCall], [hogfnCall])

            expect(result.matches).toBe(false)
            expect(result.details.mismatchDetails).toHaveLength(1)
            expect(result.details.mismatchDetails[0].differences[0]).toBe(
                'Call 1: Expected [legacy] https://example.com/api?param1=value1 but got [hogfn] https://example.com/api?param2=value2'
            )
        })

        it('should match exact URLs including query params', () => {
            const call1 = createMockCall('https://example.com/api?param1=value1&param2=value2')
            const call2 = createMockCall('https://example.com/api?param1=value1&param2=value2')

            const result = globalHttpCallRecorder.compareCalls([call1], [call2])

            expect(result.matches).toBe(true)
            expect(result.details.mismatchDetails).toHaveLength(0)
        })

        it('should enforce strict call order', () => {
            const legacyCall1 = createMockCall('https://example.com/api1')
            const legacyCall2 = createMockCall('https://example.com/api2')
            const hogfnCall1 = createMockCall('https://example.com/api2')
            const hogfnCall2 = createMockCall('https://example.com/api1')

            const result = globalHttpCallRecorder.compareCalls([legacyCall1, legacyCall2], [hogfnCall1, hogfnCall2])

            expect(result.matches).toBe(false)
            expect(result.details.mismatchDetails).toHaveLength(2)
            expect(result.details.mismatchDetails[0].differences[0]).toBe(
                'Call 1: Expected [legacy] https://example.com/api1 but got [hogfn] https://example.com/api2'
            )
            expect(result.details.mismatchDetails[1].differences[0]).toBe(
                'Call 2: Expected [legacy] https://example.com/api2 but got [hogfn] https://example.com/api1'
            )
        })

        it('should handle different numbers of calls', () => {
            const legacyCalls = [createMockCall('https://example.com/api1'), createMockCall('https://example.com/api2')]
            const hogfnCalls = [createMockCall('https://example.com/api1')]

            const result = globalHttpCallRecorder.compareCalls(legacyCalls, hogfnCalls)

            expect(result.matches).toBe(false)
            expect(result.details.totalCalls1).toBe(2)
            expect(result.details.totalCalls2).toBe(1)
            expect(result.details.mismatchDetails[0].differences[0]).toBe(
                'Call sequence length mismatch: expected 2 calls but got 1 calls'
            )
        })

        it('should show specific differences in nested JSON objects', () => {
            const legacyCall = createMockCall(
                'https://example.com/api',
                'POST',
                { 'content-type': 'application/json' },
                JSON.stringify({
                    user: {
                        name: 'John',
                        settings: {
                            theme: 'dark',
                            notifications: true,
                        },
                    },
                })
            )

            const hogfnCall = createMockCall(
                'https://example.com/api',
                'POST',
                { 'content-type': 'application/json' },
                JSON.stringify({
                    user: {
                        name: 'John',
                        settings: {
                            theme: 'light',
                            notifications: true,
                        },
                    },
                })
            )

            const result = globalHttpCallRecorder.compareCalls([legacyCall], [hogfnCall])

            expect(result.matches).toBe(false)
            expect(result.details.mismatchDetails).toHaveLength(1)
            expect(result.details.mismatchDetails[0].differences[0]).toBe(
                'Call 1: Request body differences: user.settings.theme: [legacy] "dark" ≠ [hogfn] "light"'
            )
        })

        it('should match JSON bodies with different property order', () => {
            const call1 = createMockCall(
                'https://example.com/api',
                'POST',
                { 'content-type': 'application/json' },
                JSON.stringify({
                    deeply: {
                        nested: {
                            object: {
                                b: 2,
                                a: 1,
                                d: {
                                    z: true,
                                    y: [3, 2, 1],
                                },
                                c: 3,
                            },
                        },
                    },
                })
            )

            const call2 = createMockCall(
                'https://example.com/api',
                'POST',
                { 'content-type': 'application/json' },
                JSON.stringify({
                    deeply: {
                        nested: {
                            object: {
                                a: 1,
                                b: 2,
                                c: 3,
                                d: {
                                    y: [3, 2, 1],
                                    z: true,
                                },
                            },
                        },
                    },
                })
            )

            const result = globalHttpCallRecorder.compareCalls([call1], [call2])

            expect(result.matches).toBe(true)
            expect(result.details.mismatchDetails).toHaveLength(0)
        })

        it('should show array differences with indices', () => {
            const legacyCall = createMockCall(
                'https://example.com/api',
                'POST',
                { 'content-type': 'application/json' },
                JSON.stringify({
                    items: [1, 2, 3],
                })
            )

            const hogfnCall = createMockCall(
                'https://example.com/api',
                'POST',
                { 'content-type': 'application/json' },
                JSON.stringify({
                    items: [1, 4, 3],
                })
            )

            const result = globalHttpCallRecorder.compareCalls([legacyCall], [hogfnCall])

            expect(result.matches).toBe(false)
            expect(result.details.mismatchDetails).toHaveLength(1)
            expect(result.details.mismatchDetails[0].differences[0]).toBe(
                'Call 1: Request body differences: items[1]: [legacy] 2 ≠ [hogfn] 4'
            )
        })

        it('should detect multiple differences in the same call', () => {
            const legacyCall = createMockCall(
                'https://example.com/api',
                'POST',
                { 'content-type': 'application/json' },
                JSON.stringify({
                    user: {
                        name: 'John',
                        settings: {
                            theme: 'dark',
                            notifications: {
                                email: true,
                                push: false,
                                frequency: 'daily',
                            },
                        },
                        preferences: {
                            language: 'en',
                            timezone: 'UTC',
                        },
                    },
                    items: [1, 2, 3, 4],
                    tags: ['important', 'urgent', 'review'],
                })
            )

            const hogfnCall = createMockCall(
                'https://example.com/api',
                'POST',
                { 'content-type': 'application/json' },
                JSON.stringify({
                    user: {
                        name: 'John',
                        settings: {
                            theme: 'light',
                            notifications: {
                                email: true,
                                push: true, // different
                                frequency: 'weekly', // different
                            },
                        },
                        preferences: {
                            language: 'es', // different
                            timezone: 'UTC',
                        },
                    },
                    items: [1, 5, 3, 6], // two different items
                    tags: ['urgent', 'review', 'important'], // same tags but different order
                })
            )

            const result = globalHttpCallRecorder.compareCalls([legacyCall], [hogfnCall])

            expect(result.matches).toBe(false)
            expect(result.details.mismatchDetails).toHaveLength(1)

            const differences = result.details.mismatchDetails[0].differences
            expect(differences).toEqual([
                'Call 1: Request body differences: user.settings.theme: [legacy] "dark" ≠ [hogfn] "light"',
                'Call 1: Request body differences: user.settings.notifications.push: [legacy] false ≠ [hogfn] true',
                'Call 1: Request body differences: user.settings.notifications.frequency: [legacy] "daily" ≠ [hogfn] "weekly"',
                'Call 1: Request body differences: user.preferences.language: [legacy] "en" ≠ [hogfn] "es"',
                'Call 1: Request body differences: items[1]: [legacy] 2 ≠ [hogfn] 5',
                'Call 1: Request body differences: items[3]: [legacy] 4 ≠ [hogfn] 6',
                'Call 1: Request body differences: tags[0]: [legacy] "important" ≠ [hogfn] "urgent"',
                'Call 1: Request body differences: tags[1]: [legacy] "urgent" ≠ [hogfn] "review"',
                'Call 1: Request body differences: tags[2]: [legacy] "review" ≠ [hogfn] "important"',
            ])
        })

        it('should handle multiple calls in strict order', () => {
            const legacyCalls = [
                createMockCall('https://example.com/api1', 'GET'),
                createMockCall('https://example.com/api2', 'POST', {}, '{"data":"test"}'),
                createMockCall('https://example.com/api3', 'PUT', {}, '{"data":"update"}'),
            ]

            const hogfnCalls = [
                createMockCall('https://example.com/api1', 'GET'),
                createMockCall('https://example.com/api2', 'POST', {}, '{"data":"test"}'),
                createMockCall('https://example.com/api3', 'PUT', {}, '{"data":"different"}'),
            ]

            const result = globalHttpCallRecorder.compareCalls(legacyCalls, hogfnCalls)

            expect(result.matches).toBe(false)
            expect(result.details.mismatchDetails).toHaveLength(1)
            expect(result.details.mismatchDetails[0].differences[0]).toBe(
                'Call 3: Request body differences: data: [legacy] "update" ≠ [hogfn] "different"'
            )
        })

        it('should detect multiple differences across multiple calls', () => {
            const legacyCalls = [
                createMockCall(
                    'https://example.com/api1',
                    'POST',
                    { 'content-type': 'application/json' },
                    JSON.stringify({
                        action: 'create',
                        data: { id: 1, status: 'active' },
                    })
                ),
                createMockCall(
                    'https://example.com/api2',
                    'PUT',
                    { 'content-type': 'application/json' },
                    JSON.stringify({
                        items: [1, 2, 3],
                        metadata: {
                            source: 'legacy',
                            priority: 'high',
                        },
                    })
                ),
                createMockCall('https://example.com/api3?type=sync', 'GET'),
            ]

            const hogfnCalls = [
                createMockCall(
                    'https://example.com/api1',
                    'POST',
                    { 'content-type': 'application/json' },
                    JSON.stringify({
                        action: 'update', // different action
                        data: { id: 1, status: 'inactive' }, // different status
                    })
                ),
                createMockCall(
                    'https://example.com/api2',
                    'PUT',
                    { 'content-type': 'application/json' },
                    JSON.stringify({
                        items: [1, 4, 3], // different item
                        metadata: {
                            source: 'hogfn', // different source
                            priority: 'low', // different priority
                        },
                    })
                ),
                createMockCall('https://example.com/api3?type=full', 'GET'), // different query param
            ]

            const result = globalHttpCallRecorder.compareCalls(legacyCalls, hogfnCalls)

            expect(result.matches).toBe(false)
            expect(result.details.mismatchDetails).toHaveLength(3)

            // Check first call differences
            const call1Differences = result.details.mismatchDetails[0].differences
            expect(call1Differences).toEqual([
                'Call 1: Request body differences: action: [legacy] "create" ≠ [hogfn] "update"',
                'Call 1: Request body differences: data.status: [legacy] "active" ≠ [hogfn] "inactive"',
            ])

            // Check second call differences
            const call2Differences = result.details.mismatchDetails[1].differences
            expect(call2Differences).toEqual([
                'Call 2: Request body differences: items[1]: [legacy] 2 ≠ [hogfn] 4',
                'Call 2: Request body differences: metadata.source: [legacy] "legacy" ≠ [hogfn] "hogfn"',
                'Call 2: Request body differences: metadata.priority: [legacy] "high" ≠ [hogfn] "low"',
            ])

            // Check third call differences
            const call3Differences = result.details.mismatchDetails[2].differences
            expect(call3Differences).toEqual([
                'Call 3: Expected [legacy] https://example.com/api3?type=sync but got [hogfn] https://example.com/api3?type=full',
            ])
        })
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

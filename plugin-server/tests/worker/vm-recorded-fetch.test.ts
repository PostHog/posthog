import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { trackedFetch } from '../../src/utils/fetch'
import { parseJSON } from '../../src/utils/json-parse'
import { getHttpCallRecorder, RecordedHttpCall } from '../../src/utils/recorded-fetch'
import { createPluginConfigVM } from '../../src/worker/vm/vm'
import { pluginConfig39 } from '../helpers/plugins'
import { resetTestDatabase } from '../helpers/sql'

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
    json: jest.fn().mockResolvedValue({ success: true, data: 'test data' }),
    text: jest.fn().mockResolvedValue(JSON.stringify({ success: true, data: 'test data' })),
    clone: jest.fn(function (this: any) {
        return this
    }),
}

// Mock responses for chained requests
const mockUserResponse = {
    status: 200,
    statusText: 'OK',
    headers: {
        get: jest.fn().mockReturnValue('application/json'),
        forEach: jest.fn((callback) => {
            callback('application/json', 'content-type')
        }),
        entries: jest.fn().mockReturnValue([['content-type', 'application/json']]),
    },
    json: jest.fn().mockResolvedValue({
        id: 123,
        name: 'Test User',
        email: 'test@example.com',
        preferences: { theme: 'dark' },
    }),
    text: jest.fn().mockResolvedValue(
        JSON.stringify({
            id: 123,
            name: 'Test User',
            email: 'test@example.com',
            preferences: { theme: 'dark' },
        })
    ),
    clone: jest.fn(function (this: any) {
        return this
    }),
}

const mockAnalyticsResponse = {
    status: 201,
    statusText: 'Created',
    headers: {
        get: jest.fn().mockReturnValue('application/json'),
        forEach: jest.fn((callback) => {
            callback('application/json', 'content-type')
        }),
        entries: jest.fn().mockReturnValue([['content-type', 'application/json']]),
    },
    json: jest.fn().mockResolvedValue({ success: true, message: 'Analytics data received' }),
    text: jest.fn().mockResolvedValue(JSON.stringify({ success: true, message: 'Analytics data received' })),
    clone: jest.fn(function (this: any) {
        return this
    }),
}

describe('VM with recorded fetch', () => {
    let hub: Hub
    let pluginConfig: PluginConfig
    let recordedCalls: RecordedHttpCall[]

    beforeEach(async () => {
        hub = await createHub()

        pluginConfig = { ...pluginConfig39 }

        // Reset the recorder
        getHttpCallRecorder().clearCalls()

        // Mock the fetch response
        jest.mocked(trackedFetch).mockResolvedValue(mockResponse as any)

        jest.clearAllMocks()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('records fetch calls made in onEvent', async () => {
        const indexJs = `
            async function onEvent(event) {
                await fetch('https://example.com/api/track', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ event: event.event })
                })
            }
        `
        await resetTestDatabase(indexJs)
        const vm = createPluginConfigVM(hub, pluginConfig, indexJs)

        const event: PluginEvent = {
            distinct_id: 'test_user',
            ip: '127.0.0.1',
            site_url: 'http://localhost',
            team_id: 3,
            now: new Date().toISOString(),
            event: 'test_event',
            properties: {},
        } as unknown as PluginEvent

        // Run the onEvent method
        await vm.methods.onEvent!(event as any)

        // Get the recorded calls
        recordedCalls = getHttpCallRecorder().getCalls()

        // Verify the call was recorded
        expect(recordedCalls.length).toBe(1)
        expect(recordedCalls[0].request.url).toBe('https://example.com/api/track')
        expect(recordedCalls[0].request.method).toBe('POST')
        expect(recordedCalls[0].request.headers['content-type']).toBe('application/json')
        expect(parseJSON(recordedCalls[0].request.body!)).toEqual({ event: 'test_event' })
    })

    it('records fetch calls with error responses', async () => {
        const error = new Error('Network error')
        jest.mocked(trackedFetch).mockRejectedValueOnce(error)

        const indexJs = `
            async function processEvent(event) {
                try {
                    await fetch('https://example.com/api/error')
                } catch (error) {
                    event.properties.error = error.message
                }
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = createPluginConfigVM(hub, pluginConfig, indexJs)

        const event: PluginEvent = {
            distinct_id: 'test_user',
            ip: '127.0.0.1',
            site_url: 'http://localhost',
            team_id: 3,
            now: new Date().toISOString(),
            event: 'test_event',
            properties: {},
        } as unknown as PluginEvent

        // Run the processEvent method
        const processedEvent = await vm.methods.processEvent!(event)

        // Verify the error was caught in the plugin
        expect(processedEvent?.properties?.error).toBe('Network error')

        // Get the recorded calls
        recordedCalls = getHttpCallRecorder().getCalls()

        // Verify the call was recorded with the error
        expect(recordedCalls.length).toBe(1)
        expect(recordedCalls[0].request.url).toBe('https://example.com/api/error')
        expect(recordedCalls[0].response.status).toBe(0)
        expect(recordedCalls[0].response.statusText).toBe('Network error')
        expect(recordedCalls[0].error).toBeTruthy()
        expect(recordedCalls[0].error!.message).toBe('Network error')
    })

    it('records chained HTTP requests where data from first response is used in second request', async () => {
        // First mock the user API response
        jest.mocked(trackedFetch).mockImplementationOnce(() => mockUserResponse as any)
        // Then mock the analytics API response for the second call
        jest.mocked(trackedFetch).mockImplementationOnce(() => mockAnalyticsResponse as any)

        const indexJs = `
            async function processEvent(event) {
                // First, fetch user data
                const userResponse = await fetch('https://example.com/api/users/' + event.distinct_id)
                const userData = await userResponse.json()

                // Then use the user data to make a second request
                const analyticsResponse = await fetch('https://example.com/api/analytics', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        userId: userData.id,
                        userName: userData.name,
                        userEmail: userData.email,
                        eventType: event.event,
                        eventProperties: event.properties,
                        timestamp: new Date().toISOString()
                    })
                })

                // Add the user data to the event properties
                event.properties.user_id = userData.id
                event.properties.user_name = userData.name
                event.properties.user_email = userData.email

                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = createPluginConfigVM(hub, pluginConfig, indexJs)

        const event: PluginEvent = {
            distinct_id: 'user123',
            ip: '127.0.0.1',
            site_url: 'http://localhost',
            team_id: 3,
            now: new Date().toISOString(),
            event: 'page_view',
            properties: { page: '/home' },
        } as unknown as PluginEvent

        // Run the processEvent method
        const processedEvent = await vm.methods.processEvent!(event)

        // Verify the user data was added to the event
        expect(processedEvent?.properties?.user_id).toBe(123)
        expect(processedEvent?.properties?.user_name).toBe('Test User')
        expect(processedEvent?.properties?.user_email).toBe('test@example.com')

        // Get the recorded calls
        recordedCalls = getHttpCallRecorder().getCalls()

        // Verify both calls were recorded
        expect(recordedCalls.length).toBe(2)

        // Verify the first call (GET user data)
        expect(recordedCalls[0].request.url).toBe('https://example.com/api/users/user123')
        expect(recordedCalls[0].request.method).toBe('GET')
        expect(recordedCalls[0].response.status).toBe(200)

        // Verify the second call (POST analytics data)
        expect(recordedCalls[1].request.url).toBe('https://example.com/api/analytics')
        expect(recordedCalls[1].request.method).toBe('POST')
        expect(recordedCalls[1].response.status).toBe(201)

        // Verify the second request body contains data from the first response
        const requestBody = parseJSON(recordedCalls[1].request.body!)
        expect(requestBody.userId).toBe(123)
        expect(requestBody.userName).toBe('Test User')
        expect(requestBody.userEmail).toBe('test@example.com')
        expect(requestBody.eventType).toBe('page_view')
        expect(requestBody.eventProperties).toEqual({ page: '/home' })
    })

    // Add a new test for direct JSON object body without manual stringification
    it('handles JSON object bodies directly without manual stringification', async () => {
        jest.mocked(trackedFetch).mockResolvedValueOnce(mockResponse as any)

        const indexJs = `
            async function processEvent(event) {
                // Send a request with a direct object body (not pre-stringified)
                await fetch('https://example.com/api/direct-json', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: {
                        eventName: event.event,
                        properties: event.properties,
                        timestamp: new Date().toISOString()
                    }
                })
                return event
            }
        `
        await resetTestDatabase(indexJs)
        const vm = createPluginConfigVM(hub, pluginConfig, indexJs)

        const event: PluginEvent = {
            distinct_id: 'test_user',
            ip: '127.0.0.1',
            site_url: 'http://localhost',
            team_id: 3,
            now: new Date().toISOString(),
            event: 'direct_json_test',
            properties: { test: true },
        } as unknown as PluginEvent

        // Run the processEvent method
        await vm.methods.processEvent!(event)

        // Get the recorded calls
        recordedCalls = getHttpCallRecorder().getCalls()

        // Verify the call was recorded
        expect(recordedCalls.length).toBe(1)
        expect(recordedCalls[0].request.url).toBe('https://example.com/api/direct-json')
        expect(recordedCalls[0].request.method).toBe('POST')

        // Verify the body was automatically stringified
        const requestBody = parseJSON(recordedCalls[0].request.body!)
        expect(requestBody.eventName).toBe('direct_json_test')
        expect(requestBody.properties).toEqual({ test: true })
    })
})

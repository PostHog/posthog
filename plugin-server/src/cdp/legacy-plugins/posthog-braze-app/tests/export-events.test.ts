// This App supports pushing events to Braze also, via the `onEvent` hook. It
// should send any $set attributes to Braze `/users/track` endpoint in the
// `attributes` param as well as events in the `events` property.
//
// For an $identify event with $set properties the PostHog PluginEvent json
// looks like:
//
// {
//   "event": "$identify",
//   "properties": {
//     "$set": {
//       "email": "test@posthog",
//       "name": "Test User"
//     }
//   }
// }
//
// The Braze `/users/track` endpoint expects a json payload like:
//
// {
//   "attributes": {
//     "email": "test@posthog",
//     "name": "Test User"
//   },
//   "events": []
// }
//
// For an $capture event with properties the PostHog PluginEvent json looks
// like:
//
// {
//   "event": "test event",
//   "properties": {
//     "test property": "test value"
//   }
// }
//
// The Braze `/users/track` endpoint expects a json payload like:
//
// {
//   "attributes": {},
//   "events": [
//     {
//       "name": "test event",
//       "properties": {
//         "test property": "test value"
//       }
//     }
//   ]
// }
//

import { RetryError } from '@posthog/plugin-scaffold'
import { rest } from 'msw'
import { setupServer } from 'msw/node'

import { BrazeMeta, onEvent, setupPlugin } from '../index'

const server = setupServer()

beforeAll(() => {
    console.error = jest.fn() // catch console errors
    server.listen()
})
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

test('onEvent sends $set attributes and events to Braze', async () => {
    const mockService = jest.fn()

    server.use(
        rest.post('https://rest.iad-03.braze.com/users/track', (req, res, ctx) => {
            const requestBody = req.body
            mockService(requestBody)
            return res(ctx.status(200), ctx.json({ message: 'success', attributes_processed: 1 }))
        })
    )

    // Create a meta object that we can pass into the setupPlugin and onEvent
    const meta = {
        config: {
            brazeEndpoint: 'US-03',
            eventsToExport: 'account created',
            userPropertiesToExport: 'email,name',
            eventsToExportUserPropertiesFrom: 'account created',
        },
        global: {},
    } as BrazeMeta

    await setupPlugin(meta)
    await onEvent(
        {
            event: 'account created',
            timestamp: '2023-06-16T00:00:00.00Z',
            properties: {
                $set: {
                    email: 'test@posthog',
                    name: 'Test User',
                },
                is_a_demo_user: true,
            },
            distinct_id: 'test',
            ip: '',
            site_url: '',
            team_id: 0,
            now: new Date().toISOString(),
        },
        meta
    )

    expect(mockService).toHaveBeenCalledWith({
        attributes: [
            {
                email: 'test@posthog',
                name: 'Test User',
                external_id: 'test',
            },
        ],
        events: [
            {
                // NOTE: $set properties are filtered out
                properties: {
                    is_a_demo_user: true,
                },
                external_id: 'test',
                name: 'account created',
                time: '2023-06-16T00:00:00.00Z',
            },
        ],
    })
})

test('onEvent user properties not sent on empty userPropertiesToExport', async () => {
    const mockService = jest.fn()

    server.use(
        rest.post('https://rest.iad-01.braze.com/users/track', (req, res, ctx) => {
            const requestBody = req.body
            mockService(requestBody)
            return res(ctx.status(200), ctx.json({ message: 'success', attributes_processed: 1 }))
        })
    )

    // Create a meta object that we can pass into the setupPlugin and onEvent
    const meta = {
        config: {
            brazeEndpoint: 'US-01',
            eventsToExport: 'account created',
            eventsToExportUserPropertiesFrom: 'account created',
        },
        global: {},
    } as BrazeMeta

    await setupPlugin(meta)
    await onEvent(
        {
            event: 'account created',
            timestamp: '2023-06-16T00:00:00.00Z',
            properties: {
                $set: {
                    email: 'test@posthog',
                    name: 'Test User',
                },
                is_a_demo_user: true,
            },
            distinct_id: 'test',
            ip: '',
            site_url: '',
            team_id: 0,
            now: new Date().toISOString(),
        },
        meta
    )

    expect(mockService).toHaveBeenCalledWith({
        attributes: [],
        events: [
            {
                // NOTE: $set properties are filtered out
                properties: {
                    is_a_demo_user: true,
                },
                external_id: 'test',
                name: 'account created',
                time: '2023-06-16T00:00:00.00Z',
            },
        ],
    })
})

test('onEvent user properties not sent on empty eventsToExportUserPropertiesFrom', async () => {
    const mockService = jest.fn()

    server.use(
        rest.post('https://rest.iad-01.braze.com/users/track', (req, res, ctx) => {
            const requestBody = req.body
            mockService(requestBody)
            return res(ctx.status(200), ctx.json({ message: 'success', attributes_processed: 1 }))
        })
    )

    // Create a meta object that we can pass into the setupPlugin and onEvent
    const meta = {
        config: {
            brazeEndpoint: 'US-01',
            eventsToExport: 'account created',
            userPropertiesToExport: 'email,name',
        },
        global: {},
    } as BrazeMeta

    await setupPlugin(meta)
    await onEvent(
        {
            event: 'account created',
            timestamp: '2023-06-16T00:00:00.00Z',
            properties: {
                $set: {
                    email: 'test@posthog',
                    name: 'Test User',
                },
                is_a_demo_user: true,
            },
            distinct_id: 'test',
            ip: '',
            site_url: '',
            team_id: 0,
            now: new Date().toISOString(),
        },
        meta
    )

    expect(mockService).toHaveBeenCalledWith({
        attributes: [],
        events: [
            {
                // NOTE: $set properties are filtered out
                properties: {
                    is_a_demo_user: true,
                },
                external_id: 'test',
                name: 'account created',
                time: '2023-06-16T00:00:00.00Z',
            },
        ],
    })
})

test('onEvent user properties are passed for $identify event even if $identify is not reported', async () => {
    const mockService = jest.fn()

    server.use(
        rest.post('https://rest.fra-01.braze.eu/users/track', (req, res, ctx) => {
            const requestBody = req.body
            mockService(requestBody)
            return res(ctx.status(200), ctx.json({ message: 'success', attributes_processed: 1 }))
        })
    )

    // Create a meta object that we can pass into the setupPlugin and onEvent
    const meta = {
        config: {
            brazeEndpoint: 'EU-01',
            eventsToExport: 'account created',
            userPropertiesToExport: 'email',
            eventsToExportUserPropertiesFrom: 'account created,$identify',
        },
        global: {},
    } as BrazeMeta

    await setupPlugin(meta)
    await onEvent(
        {
            event: '$identify',
            timestamp: '2023-06-16T00:00:00.00Z',
            properties: {
                $set: {
                    email: 'test@posthog',
                    name: 'Test User',
                },
                is_a_demo_user: true,
            },
            distinct_id: 'test',
            ip: '',
            site_url: '',
            team_id: 0,
            now: new Date().toISOString(),
        },
        meta
    )

    expect(mockService).toHaveBeenCalledWith({
        attributes: [
            {
                email: 'test@posthog',
                external_id: 'test',
            },
        ],
        events: [],
    })
})

test('onEvent user properties are not passed for non-whitelisted events', async () => {
    const mockService = jest.fn()

    server.use(
        rest.post('https://rest.iad-01.braze.com/users/track', (req, res, ctx) => {
            const requestBody = req.body
            mockService(requestBody)
            return res(ctx.status(200), ctx.json({ message: 'success', attributes_processed: 1 }))
        })
    )

    // Create a meta object that we can pass into the setupPlugin and onEvent
    const meta = {
        config: {
            brazeEndpoint: 'US-01',
            eventsToExport: 'account created',
            userPropertiesToExport: 'email',
            eventsToExportUserPropertiesFrom: 'account created',
        },
        global: {},
    } as BrazeMeta

    await setupPlugin(meta)
    await onEvent(
        {
            event: '$identify',
            timestamp: '2023-06-16T00:00:00.00Z',
            properties: {
                $set: {
                    email: 'test@posthog',
                    name: 'Test User',
                },
                is_a_demo_user: true,
            },
            distinct_id: 'test',
            ip: '',
            site_url: '',
            team_id: 0,
            now: new Date().toISOString(),
        },
        meta
    )

    expect(mockService).not.toHaveBeenCalled()
})

test('Braze API error (e.g. 400) are not retried', async () => {
    // NOTE: We only retry intermittent errors (e.g. 5xx), 4xx errors are most likely going to continue failing if retried
    const mockService = jest.fn()

    const errorResponse = {
        errors: [
            {
                type: "'external_id' or 'braze_id' or 'user_alias' is required",
                input_array: 'attributes',
                index: 0,
            },
        ],
    }

    server.use(
        rest.post('https://rest.iad-02.braze.com/users/track', (req, res, ctx) => {
            const requestBody = req.body
            mockService(requestBody)
            return res(ctx.status(400), ctx.json(errorResponse))
        })
    )

    // Create a meta object that we can pass into the setupPlugin and onEvent
    const meta = {
        config: {
            brazeEndpoint: 'US-02',
            eventsToExport: 'account created',
            userPropertiesToExport: 'email',
            eventsToExportUserPropertiesFrom: 'account created,$identify',
        },
        global: {},
    } as BrazeMeta

    await setupPlugin(meta)
    await onEvent(
        {
            event: '$identify',
            timestamp: '2023-06-16T00:00:00.00Z',
            properties: {
                $set: {
                    email: 'test@posthog',
                    name: 'Test User',
                },
                is_a_demo_user: true,
            },
            distinct_id: 'test',
            ip: '',
            site_url: '',
            team_id: 0,
            now: new Date().toISOString(),
            uuid: 'event_123',
        },
        meta
    )
    expect(console.error).toHaveBeenCalledWith(
        'Braze API error (not retried): ',
        errorResponse,
        '/users/track',
        expect.anything(),
        expect.any(String)
    )
})

test('Braze offline error (500 response)', async () => {
    server.use(
        rest.post('https://rest.iad-02.braze.com/users/track', (_, res, ctx) => {
            return res(ctx.status(500), ctx.json({}))
        })
    )

    // Create a meta object that we can pass into the setupPlugin and onEvent
    const meta = {
        config: {
            brazeEndpoint: 'US-02',
            eventsToExport: 'account created',
            userPropertiesToExport: 'email',
            eventsToExportUserPropertiesFrom: 'account created,$identify',
        },
        global: {},
    } as BrazeMeta

    await setupPlugin(meta)
    try {
        await onEvent(
            {
                event: '$identify',
                timestamp: '2023-06-16T00:00:00.00Z',
                properties: {
                    $set: {
                        email: 'test@posthog',
                        name: 'Test User',
                    },
                    is_a_demo_user: true,
                },
                distinct_id: 'test',
                ip: '',
                site_url: '',
                team_id: 0,
                now: new Date().toISOString(),
                uuid: 'id_123',
            },
            meta
        )
        throw new Error('Should not reach here')
    } catch (e) {
        expect(e instanceof RetryError).toBeTruthy()
        // @ts-ignore
        expect(e.message).toMatch('Service is down, retry later. Request ID: ')
    }
})

test('Braze offline error (network error)', async () => {
    server.use(
        rest.post('https://rest.iad-02.braze.com/users/track', (_, res) => {
            return res.networkError('Failed to connect')
        })
    )

    // Create a meta object that we can pass into the setupPlugin and onEvent
    const meta = {
        config: {
            brazeEndpoint: 'US-02',
            eventsToExport: 'account created',
            userPropertiesToExport: 'email',
            eventsToExportUserPropertiesFrom: 'account created,$identify',
        },
        global: {},
    } as BrazeMeta

    await setupPlugin(meta)
    try {
        await onEvent(
            {
                event: '$identify',
                timestamp: '2023-06-16T00:00:00.00Z',
                properties: {
                    $set: {
                        email: 'test@posthog',
                        name: 'Test User',
                    },
                    is_a_demo_user: true,
                },
                distinct_id: 'test',
                ip: '',
                site_url: '',
                team_id: 0,
                now: new Date().toISOString(),
                uuid: 'id_123',
            },
            meta
        )
        throw new Error('Should not reach here')
    } catch (e) {
        expect(e instanceof RetryError).toBeTruthy()
        // @ts-ignore
        expect(e.message).toMatch('Fetch failed, retrying.')
    }
})

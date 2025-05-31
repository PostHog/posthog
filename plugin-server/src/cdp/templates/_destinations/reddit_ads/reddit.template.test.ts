import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './reddit.template'

jest.setTimeout(2 * 60 * 1000)

describe('reddit template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate())
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('works with single product event', async () => {
        const response = await tester.invokeMapping(
            'Product Viewed',
            {
                accountId: 'pixel-id',
                conversionsAccessToken: 'access-token',
            },
            {
                event: {
                    properties: {
                        product_id: '1bdfef47c9724b58b6831933',
                        sku: '43431-18',
                        category: 'merch',
                        name: 'Tactical black t-shirt',
                        brand: 'PostHog',
                        variant: 'dark',
                        price: 30,
                        quantity: 1,
                        coupon: 'BLACKFRIDAY',
                        currency: 'usd',
                        position: 3,
                        value: 30,
                        url: 'https://posthog.com/merch?product=tactical-black-t-shirt',
                        image_url:
                            'https://cdn.shopify.com/s/files/1/0452/0935/4401/files/darkmode_tee_5_1000x1000_crop_center.jpg?v=1732211354',
                        $current_url: 'https://posthog.com/merch?product=tactical-black-t-shirt',
                    },
                    event: 'Product Viewed',
                    uuid: 'event-id',
                    timestamp: '2025-01-01T00:00:00Z',
                    distinct_id: 'distinct-id',
                    elements_chain: '',
                    url: 'https://us.posthog.com/projects/1/events/1234',
                },
                person: {
                    id: 'person-id',
                    properties: {
                        email: 'example@posthog.com',
                        ttclid: 'tiktok-id',
                        phone: '+1234567890',
                        external_id: '1234567890',
                        first_name: 'Max',
                        last_name: 'AI',
                    },
                    url: 'https://us.posthog.com/projects/1/persons/1234',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"test_mode":false,"events":[{"event_at":"2025-01-01T00:00:00Z","event_type":{"tracking_type":"ViewContent"},"user":{"email":"example@posthog.com","screen_dimensions":{"width":null,"height":null}},"event_metadata":{"conversion_id":"event-id","products":[{"id":"1bdfef47c9724b58b6831933","category":"merch","name":"Tactical black t-shirt"}],"value":30,"currency":"usd"}}]}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "User-Agent": "hog:com.posthog.cdp:0.0.1 (by /u/PostHogTeam)",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://ads-api.reddit.com/api/v2.0/conversions/events/pixel-id",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: '{"status": "OK"}',
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('works with empty product properties', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                accountId: 'pixel-id',
                conversionsAccessToken: 'access-token',
            },
            {
                event: {
                    properties: {},
                    event: 'Order Completed',
                    uuid: 'event-id',
                    timestamp: '2025-01-01T00:00:00Z',
                    distinct_id: 'distinct-id',
                    elements_chain: '',
                    url: 'https://us.posthog.com/projects/1/events/1234',
                },
                person: {
                    id: 'person-id',
                    properties: {
                        email: 'example@posthog.com',
                        ttclid: 'tiktok-id',
                    },
                    url: 'https://us.posthog.com/projects/1/persons/1234',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"test_mode":false,"events":[{"event_at":"2025-01-01T00:00:00Z","event_type":{"tracking_type":"Purchase"},"user":{"email":"example@posthog.com","screen_dimensions":{"width":null,"height":null}},"event_metadata":{"conversion_id":"event-id"}}]}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "User-Agent": "hog:com.posthog.cdp:0.0.1 (by /u/PostHogTeam)",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://ads-api.reddit.com/api/v2.0/conversions/events/pixel-id",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: '{"status": "OK"}',
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('handles error responses', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                accountId: 'pixel-id',
                conversionsAccessToken: 'access-token',
            },
            {
                event: {
                    properties: {},
                    event: 'Order Completed',
                    uuid: 'event-id',
                    timestamp: '2025-01-01T00:00:00Z',
                    distinct_id: 'distinct-id',
                    elements_chain: '',
                    url: 'https://us.posthog.com/projects/1/events/1234',
                },
                person: {
                    id: 'person-id',
                    properties: {
                        email: 'example@posthog.com',
                        ttclid: 'tiktok-id',
                    },
                    url: 'https://us.posthog.com/projects/1/persons/1234',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"test_mode":false,"events":[{"event_at":"2025-01-01T00:00:00Z","event_type":{"tracking_type":"Purchase"},"user":{"email":"example@posthog.com","screen_dimensions":{"width":null,"height":null}},"event_metadata":{"conversion_id":"event-id"}}]}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "User-Agent": "hog:com.posthog.cdp:0.0.1 (by /u/PostHogTeam)",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://ads-api.reddit.com/api/v2.0/conversions/events/pixel-id",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 400, headers: {} },
            body: '{"status": "Something went wrong", "message": "Invalid event properties"}',
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from https://ads-api.reddit.com (status 400): {'status': 'Something went wrong', 'message': 'Invalid event properties'}"`
        )
    })

    it('handles missing pixel id', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                conversionsAccessToken: 'access-token',
            },
            {
                event: {
                    properties: {},
                    event: 'Order Completed',
                    uuid: 'event-id',
                    timestamp: '2025-01-01T00:00:00Z',
                    distinct_id: 'distinct-id',
                    elements_chain: '',
                    url: 'https://us.posthog.com/projects/1/events/1234',
                },
                person: {
                    id: 'person-id',
                    properties: {
                        email: 'example@posthog.com',
                        ttclid: 'tiktok-id',
                    },
                    url: 'https://us.posthog.com/projects/1/persons/1234',
                },
            }
        )

        expect(response.error).toMatchInlineSnapshot(`"Account ID and access token are required"`)
        expect(response.finished).toEqual(true)
    })

    it('handles missing access token', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                accountId: 'pixel-id',
            },
            {
                event: {
                    properties: {},
                    event: 'Order Completed',
                    uuid: 'event-id',
                    timestamp: '2025-01-01T00:00:00Z',
                    distinct_id: 'distinct-id',
                    elements_chain: '',
                    url: 'https://us.posthog.com/projects/1/events/1234',
                },
                person: {
                    id: 'person-id',
                    properties: {
                        email: 'example@posthog.com',
                        ttclid: 'tiktok-id',
                    },
                    url: 'https://us.posthog.com/projects/1/persons/1234',
                },
            }
        )

        expect(response.error).toMatchInlineSnapshot(`"Account ID and access token are required"`)
        expect(response.finished).toEqual(true)
    })
})

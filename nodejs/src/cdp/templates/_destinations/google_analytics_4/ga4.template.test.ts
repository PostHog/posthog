import { TemplateTester } from '../../test/test-helpers'
import { template } from './ga4.template'

jest.setTimeout(60 * 1000)

describe('google analytics 4 template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('sends a page_view event', async () => {
        const response = await tester.invokeMapping(
            'Page view',
            {
                measurementId: 'G-XXXXXXXXXX',
                apiSecret: 'test-api-secret',
            },
            {
                event: {
                    event: '$pageview',
                    properties: {
                        $current_url: 'https://posthog.com/docs',
                        $referrer: 'https://google.com',
                        title: 'PostHog Docs',
                    },
                    distinct_id: 'user-123',
                    uuid: 'event-id',
                    timestamp: '2025-01-01T00:00:00Z',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"client_id":"user-123","events":[{"name":"page_view","params":{"page_location":"https://posthog.com/docs","page_referrer":"https://google.com","page_title":"PostHog Docs"}}]}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://www.google-analytics.com/mp/collect?measurement_id=G-XXXXXXXXXX&api_secret=test-api-secret",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 204,
            body: {},
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('sends a custom event with user_id', async () => {
        const response = await tester.invokeMapping(
            'Custom event',
            {
                measurementId: 'G-XXXXXXXXXX',
                apiSecret: 'test-api-secret',
            },
            {
                event: {
                    event: 'purchase',
                    properties: {
                        value: '99.99',
                        currency: 'USD',
                    },
                    distinct_id: 'user-123',
                    uuid: 'event-id',
                    timestamp: '2025-01-01T00:00:00Z',
                },
            },
            {
                userId: '{event.distinct_id}',
                eventParameters: {
                    value: '{event.properties.value}',
                    currency: '{event.properties.currency}',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"client_id":"user-123","events":[{"name":"purchase","params":{"value":"99.99","currency":"USD"}}],"user_id":"user-123"}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://www.google-analytics.com/mp/collect?measurement_id=G-XXXXXXXXXX&api_secret=test-api-secret",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 204,
            body: {},
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('skips when clientId is empty', async () => {
        const response = await tester.invokeMapping(
            'Custom event',
            {
                measurementId: 'G-XXXXXXXXXX',
                apiSecret: 'test-api-secret',
            },
            {
                event: {
                    event: 'test_event',
                    distinct_id: '',
                    uuid: 'event-id',
                    timestamp: '2025-01-01T00:00:00Z',
                },
                person: {
                    properties: {},
                },
            }
        )

        expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toMatchInlineSnapshot(`
            [
              "Empty \`clientId\`. Skipping...",
            ]
        `)
        expect(response.finished).toEqual(true)
    })

    it('handles error responses', async () => {
        const response = await tester.invokeMapping(
            'Custom event',
            {
                measurementId: 'G-XXXXXXXXXX',
                apiSecret: 'test-api-secret',
            },
            {
                event: {
                    event: 'test_event',
                    distinct_id: 'user-123',
                    uuid: 'event-id',
                    timestamp: '2025-01-01T00:00:00Z',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: 'Invalid measurement_id' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from Google Analytics 4 (status 400): {'error': 'Invalid measurement_id'}"`
        )
    })
})

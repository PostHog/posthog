import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './google.template'

jest.setTimeout(2 * 60 * 1000)

describe('google template', () => {
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
            'Signed Up',
            {
                oauth: {
                    access_token: 'access-token',
                },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
            },
            {
                event: {
                    properties: {
                        $current_url: 'https://posthog.com/merch?product=tactical-black-t-shirt',
                        currency: 'USD',
                        value: '100',
                        order_id: '1234567890',
                    },
                    event: 'Signed Up',
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
                        gclid: 'google-id',
                        phone: '+1234567890',
                        external_id: '1234567890',
                        first_name: 'Max',
                        last_name: 'AI',
                    },
                    url: 'https://us.posthog.com/projects/1/persons/1234',
                },
            },
            {
                currencyCode: '{event.properties.currency}',
                conversionValue: '{event.properties.value}',
                orderId: '{event.properties.order_id}',
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queue).toEqual('fetch')
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"conversions":[{"gclid":"google-id","conversion_action":"customers/1231231234/conversionActions/123456789","conversion_date_time":"2025-01-01 00:00:00+00:00","conversion_value":"100","currency_code":"USD","order_id":"1234567890"}],"partialFailure":true}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "developer-token": undefined,
                "login-customer-id": "5675675678",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://googleads.googleapis.com/v18/customers/1231231234:uploadClickConversions",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 200, headers: {} },
            body: '{"status": "OK"}',
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('works with empty properties', async () => {
        const response = await tester.invokeMapping(
            'Signed Up',
            {
                oauth: {
                    access_token: 'access-token',
                },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
            },
            {
                event: {
                    properties: {},
                    event: 'Signed Up',
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
                        gclid: 'gclid-id',
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
              "body": "{"conversions":[{"gclid":"gclid-id","conversion_action":"customers/1231231234/conversionActions/123456789","conversion_date_time":"2025-01-01 00:00:00+00:00"}],"partialFailure":true}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "developer-token": undefined,
                "login-customer-id": "5675675678",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://googleads.googleapis.com/v18/customers/1231231234:uploadClickConversions",
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
            'Signed Up',
            {
                oauth: {
                    access_token: 'access-token',
                },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
                currencyCode: '{event.properties.currency}',
            },
            {
                event: {
                    properties: {},
                    event: 'Signed Up',
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
                        gclid: 'google-id',
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
              "body": "{"conversions":[{"gclid":"google-id","conversion_action":"customers/1231231234/conversionActions/123456789","conversion_date_time":"2025-01-01 00:00:00+00:00"}],"partialFailure":true}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "developer-token": undefined,
                "login-customer-id": "5675675678",
              },
              "method": "POST",
              "return_queue": "hog",
              "url": "https://googleads.googleapis.com/v18/customers/1231231234:uploadClickConversions",
            }
        `)

        const fetchResponse = tester.invokeFetchResponse(response.invocation, {
            response: { status: 400, headers: {} },
            body: '{"status": "Something went wrong", "message": "Invalid event properties"}',
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from googleads.googleapis.com (status 400): {'status': 'Something went wrong', 'message': 'Invalid event properties'}"`
        )
    })

    it('handles missing gclid', async () => {
        const response = await tester.invokeMapping(
            'Signed Up',
            {
                oauth: {
                    access_token: 'access-token',
                },
                customerId: '1231231234/5675675678',
                conversionActionId: '123456789',
            },
            {
                event: {
                    properties: {},
                    event: 'Signed Up',
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
                    },
                    url: 'https://us.posthog.com/projects/1/persons/1234',
                },
            }
        )

        expect(response.logs).toMatchInlineSnapshot(`
            [
              {
                "level": "debug",
                "message": "Executing function",
                "timestamp": "2025-01-01T01:00:00.000+01:00",
              },
              {
                "level": "info",
                "message": "Empty \`gclid\`. Skipping...",
                "timestamp": "2025-01-01T01:00:00.000+01:00",
              },
              {
                "level": "debug",
                "message": "Function completed in 0ms. Sync: 0ms. Mem: 34 bytes. Ops: 10. Event: 'https://us.posthog.com/projects/1/events/1234'",
                "timestamp": "2025-01-01T01:00:00.000+01:00",
              },
            ]
        `)
        expect(response.finished).toEqual(true)
    })
})

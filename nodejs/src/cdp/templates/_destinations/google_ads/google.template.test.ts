import { DateTime, Settings } from 'luxon'

import { TemplateTester, createAdDestinationPayload } from '../../test/test-helpers'
import { template } from './google.template'

jest.setTimeout(60 * 1000)

describe('google template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        Settings.defaultZone = 'UTC'
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    afterEach(() => {
        Settings.defaultZone = 'system'
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
            createAdDestinationPayload({
                event: {
                    properties: {
                        $current_url: 'https://posthog.com/merch?product=tactical-black-t-shirt',
                        currency: 'USD',
                        value: '100',
                        order_id: '1234567890',
                    },
                },
                person: {
                    properties: {
                        phone: '+1234567890',
                        external_id: '1234567890',
                        first_name: 'Max',
                        last_name: 'AI',
                    },
                },
            }),
            {
                currencyCode: '{event.properties.currency}',
                conversionValue: '{event.properties.value}',
                orderId: '{event.properties.order_id}',
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"conversions":[{"gclid":"google-id","conversion_action":"customers/1231231234/conversionActions/123456789","conversion_date_time":"2025-01-01 00:00:00+00:00","conversion_value":"100","currency_code":"USD","order_id":"1234567890"}],"partialFailure":true}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "login-customer-id": "5675675678",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://googleads.googleapis.com/v21/customers/1231231234:uploadClickConversions",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
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
            createAdDestinationPayload()
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"conversions":[{"gclid":"google-id","conversion_action":"customers/1231231234/conversionActions/123456789","conversion_date_time":"2025-01-01 00:00:00+00:00"}],"partialFailure":true}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "login-customer-id": "5675675678",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://googleads.googleapis.com/v21/customers/1231231234:uploadClickConversions",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
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
            createAdDestinationPayload()
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"conversions":[{"gclid":"google-id","conversion_action":"customers/1231231234/conversionActions/123456789","conversion_date_time":"2025-01-01 00:00:00+00:00"}],"partialFailure":true}",
              "headers": {
                "Authorization": "Bearer access-token",
                "Content-Type": "application/json",
                "login-customer-id": "5675675678",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://googleads.googleapis.com/v21/customers/1231231234:uploadClickConversions",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { status: 'Something went wrong', message: 'Invalid event properties' },
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
            createAdDestinationPayload({
                person: {
                    properties: {
                        gclid: null,
                    },
                },
            })
        )

        expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toMatchInlineSnapshot(`
            [
              "Empty \`gclid\`. Skipping...",
            ]
        `)
        expect(response.finished).toEqual(true)
    })
})

import { DateTime } from 'luxon'

import { createAdDestinationPayload, TemplateTester } from '../../test/test-helpers'
import { template } from './tiktok.template'

jest.setTimeout(2 * 60 * 1000)

describe('tiktok template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('works with single product event', async () => {
        const response = await tester.invokeMapping(
            'Product Viewed',
            {
                accessToken: 'access-token',
                pixelId: 'pixel-id',
            },
            createAdDestinationPayload({
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
                },
            })
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"event_source":"web","event_source_id":"pixel-id","data":[{"event":"ViewContent","event_time":1735689600,"event_id":"event-id","user":{"email":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","first_name":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","last_name":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","phone":"422ce82c6fc1724ac878042f7d055653ab5e983d186e616826a72d4384b68af8","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10","ttclid":"tiktok-id"},"properties":{"content_ids":["43431-18"],"contents":[{"price":30,"content_id":"43431-18","content_category":"merch","content_name":"Tactical black t-shirt","brand":"PostHog"}],"content_type":"product","currency":"usd","value":30,"num_items":1},"page":{"url":"https://posthog.com/merch?product=tactical-black-t-shirt"}}]}",
              "headers": {
                "Access-Token": "access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://business-api.tiktok.com/open_api/v1.3/event/track/",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('works with multi product event', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                accessToken: 'access-token',
                pixelId: 'pixel-id',
            },
            createAdDestinationPayload({
                event: {
                    properties: {
                        checkout_id: 'e461659ed1714b9ebc3299ae',
                        order_id: '3e94e72c0a7443e9b51155a3',
                        affiliation: 'Shopify',
                        total: 80,
                        subtotal: 75,
                        revenue: 90.0,
                        shipping: 3,
                        tax: 2,
                        discount: 15,
                        coupon: 'BLACKFRIDAY',
                        currency: 'USD',
                        products: [
                            {
                                product_id: 'c6e74d89b70b4972b867eb62',
                                sku: '18499-12',
                                category: 'merch',
                                name: 'Data warehouse t-shirt',
                                brand: 'PostHog',
                                variant: 'light',
                                price: 30,
                                quantity: 1,
                                position: 3,
                                url: 'https://posthog.com/merch?product=data-warehouse-t-shirt',
                                image_url:
                                    'https://cdn.shopify.com/s/files/1/0452/0935/4401/files/DSC07095_1017x1526_crop_center.jpg?v=1709570895',
                            },
                            {
                                product_id: '101c66c0b37f47bc9c75561f',
                                sku: '94839-23',
                                category: 'merch',
                                name: 'Danger t-shirt',
                                brand: 'PostHog',
                                variant: 'blue',
                                price: 30,
                                quantity: 2,
                                position: 3,
                                url: 'https://posthog.com/merch?product=danger-t-shirt',
                                image_url:
                                    'https://cdn.shopify.com/s/files/1/0452/0935/4401/files/cautiontee4_1000x1000_crop_center.jpg?v=1732041736',
                            },
                        ],
                    },
                },
            })
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"event_source":"web","event_source_id":"pixel-id","data":[{"event":"CompletePayment","event_time":1735689600,"event_id":"event-id","user":{"email":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","first_name":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","last_name":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","phone":"422ce82c6fc1724ac878042f7d055653ab5e983d186e616826a72d4384b68af8","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10","ttclid":"tiktok-id"},"properties":{"content_ids":["18499-12","94839-23"],"contents":[{"price":30,"content_id":"18499-12","content_category":"merch","content_name":"Data warehouse t-shirt","brand":"PostHog"},{"price":30,"content_id":"94839-23","content_category":"merch","content_name":"Danger t-shirt","brand":"PostHog"}],"content_type":"product","currency":"USD","value":90,"num_items":3,"order_id":"3e94e72c0a7443e9b51155a3"},"page":{}}]}",
              "headers": {
                "Access-Token": "access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://business-api.tiktok.com/open_api/v1.3/event/track/",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('works with empty product properties', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                accessToken: 'access-token',
                pixelId: 'pixel-id',
            },
            createAdDestinationPayload()
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"event_source":"web","event_source_id":"pixel-id","data":[{"event":"CompletePayment","event_time":1735689600,"event_id":"event-id","user":{"email":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","first_name":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","last_name":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","phone":"422ce82c6fc1724ac878042f7d055653ab5e983d186e616826a72d4384b68af8","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10","ttclid":"tiktok-id"},"properties":{"content_type":"product","currency":"USD","num_items":0},"page":{}}]}",
              "headers": {
                "Access-Token": "access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://business-api.tiktok.com/open_api/v1.3/event/track/",
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
            'Order Completed',
            {
                accessToken: 'access-token',
                pixelId: 'pixel-id',
            },
            createAdDestinationPayload()
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"event_source":"web","event_source_id":"pixel-id","data":[{"event":"CompletePayment","event_time":1735689600,"event_id":"event-id","user":{"email":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","first_name":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","last_name":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","phone":"422ce82c6fc1724ac878042f7d055653ab5e983d186e616826a72d4384b68af8","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10","ttclid":"tiktok-id"},"properties":{"content_type":"product","currency":"USD","num_items":0},"page":{}}]}",
              "headers": {
                "Access-Token": "access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://business-api.tiktok.com/open_api/v1.3/event/track/",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { status: 'Something went wrong', message: 'Invalid event properties' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from business-api.tiktok.com (status 400): {'status': 'Something went wrong', 'message': 'Invalid event properties'}"`
        )
    })

    it('sends test event code if specified', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                accessToken: 'access-token',
                pixelId: 'pixel-id',
                testEventCode: 'test-event-code',
            },
            createAdDestinationPayload()
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"event_source":"web","event_source_id":"pixel-id","data":[{"event":"CompletePayment","event_time":1735689600,"event_id":"event-id","user":{"email":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","first_name":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","last_name":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","phone":"422ce82c6fc1724ac878042f7d055653ab5e983d186e616826a72d4384b68af8","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10","ttclid":"tiktok-id"},"properties":{"content_type":"product","currency":"USD","num_items":0},"page":{}}],"test_event_code":"test-event-code"}",
              "headers": {
                "Access-Token": "access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://business-api.tiktok.com/open_api/v1.3/event/track/",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('sensitive values are hashed', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                accessToken: 'access-token',
                pixelId: 'pixel-id',
            },
            createAdDestinationPayload({
                event: {
                    properties: {
                        $ip: '123.123.123.123',
                        $raw_user_agent:
                            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
                    },
                },
            })
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"event_source":"web","event_source_id":"pixel-id","data":[{"event":"CompletePayment","event_time":1735689600,"event_id":"event-id","user":{"email":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","first_name":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","last_name":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","phone":"422ce82c6fc1724ac878042f7d055653ab5e983d186e616826a72d4384b68af8","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10","ttclid":"tiktok-id","ip":"123.123.123.123","user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"},"properties":{"content_type":"product","currency":"USD","num_items":0},"page":{}}]}",
              "headers": {
                "Access-Token": "access-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://business-api.tiktok.com/open_api/v1.3/event/track/",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { status: 'OK' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it.each([
        ['missing pixel id', { accessToken: 'access-token' }],
        ['missing access token', { pixelId: 'pixel-id' }],
    ])('handles %s', async (_, settings) => {
        const response = await tester.invokeMapping('Order Completed', settings, createAdDestinationPayload())

        expect(response.error).toMatchInlineSnapshot(`"Pixel ID and access token are required"`)
        expect(response.finished).toEqual(true)
    })
})

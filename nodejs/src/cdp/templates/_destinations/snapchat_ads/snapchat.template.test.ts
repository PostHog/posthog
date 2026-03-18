import { DateTime } from 'luxon'

import { TemplateTester, createAdDestinationPayload } from '../../test/test-helpers'
import { template } from './snapchat.template'

jest.setTimeout(2 * 60 * 1000)

describe('snapchat template', () => {
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
                oauth: {
                    access_token: 'access-token',
                },
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
                person: {
                    properties: {
                        phone: '+1234567890',
                        external_id: '1234567890',
                        first_name: 'Max',
                        last_name: 'AI',
                    },
                },
            })
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"VIEW_CONTENT","action_source":"WEB","event_time":1735689600,"event_source_url":"https://posthog.com/merch?product=tactical-black-t-shirt","user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646","sc_click_id":"snapchat-id","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10"},"custom_data":{"value":30,"currency":"usd","content_ids":"43431-18","content_category":"merch","contents":[{"item_price":30,"id":"43431-18","quantity":1,"delivery_category":"normal"}],"num_items":1,"event_id":"event-id"}}]}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://tr.snapchat.com/v3/pixel-id/events?access_token=access-token",
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
                oauth: {
                    access_token: 'access-token',
                },
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
                    event: 'Order Completed',
                },
            })
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"PURCHASE","action_source":"WEB","event_time":1735689600,"event_source_url":null,"user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646","sc_click_id":"snapchat-id","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10"},"custom_data":{"value":90,"currency":"USD","content_ids":["18499-12","94839-23"],"content_category":["merch","merch"],"contents":[{"item_price":30,"id":"18499-12","quantity":1,"delivery_category":"normal"},{"item_price":30,"id":"94839-23","quantity":2,"delivery_category":"normal"}],"num_items":3,"event_id":"event-id"}}]}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://tr.snapchat.com/v3/pixel-id/events?access_token=access-token",
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
                oauth: {
                    access_token: 'access-token',
                },
                pixelId: 'pixel-id',
            },
            createAdDestinationPayload()
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"PURCHASE","action_source":"WEB","event_time":1735689600,"event_source_url":null,"user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646","sc_click_id":"snapchat-id","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10"},"custom_data":{"num_items":0,"event_id":"event-id"}}]}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://tr.snapchat.com/v3/pixel-id/events?access_token=access-token",
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
                oauth: {
                    access_token: 'access-token',
                },
                pixelId: 'pixel-id',
            },
            createAdDestinationPayload()
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"PURCHASE","action_source":"WEB","event_time":1735689600,"event_source_url":null,"user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646","sc_click_id":"snapchat-id","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10"},"custom_data":{"num_items":0,"event_id":"event-id"}}]}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://tr.snapchat.com/v3/pixel-id/events?access_token=access-token",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { status: 'Something went wrong', message: 'Invalid event properties' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from tr.snapchat.com (status 400): {'status': 'Something went wrong', 'message': 'Invalid event properties'}"`
        )
    })

    it('test event mode working', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            {
                oauth: {
                    access_token: 'access-token',
                },
                pixelId: 'pixel-id',
                testEventMode: true,
            },
            createAdDestinationPayload()
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"PURCHASE","action_source":"WEB","event_time":1735689600,"event_source_url":null,"user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646","sc_click_id":"snapchat-id","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10"},"custom_data":{"num_items":0,"event_id":"event-id"}}]}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://tr.snapchat.com/v3/pixel-id/events/validate?access_token=access-token",
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
                oauth: {
                    access_token: 'access-token',
                },
                pixelId: 'pixel-id',
            },
            createAdDestinationPayload({
                event: {
                    properties: {
                        $ip: '123.123.123.123',
                        $raw_user_agent:
                            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
                    },
                    event: 'Order Completed',
                },
                person: {
                    properties: {
                        email: 'example@posthog.com',
                        sccid: 'snapchat-id',
                        phone: '+1234567890',
                        first_name: 'Max',
                        last_name: 'AI',
                        $geoip_city_name: 'San Francisco',
                        $geoip_subdivision_1_code: 'CA',
                        $geoip_country_code: 'US',
                        $geoip_postal_code: '94101',
                    },
                },
            })
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"PURCHASE","action_source":"WEB","event_time":1735689600,"event_source_url":null,"user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646","sc_click_id":"snapchat-id","client_user_agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566","ct":"1a6bd4d9d79dc0a79b53795c70d3349fa9e38968a3fbefbfe8783efb1d2b6aac","st":"6959097001d10501ac7d54c0bdb8db61420f658f2922cc26e46d536119a31126","country":"79adb2a2fce5c6ba215fe5f27f532d4e7edbac4b6a5e09e1ef3a08084a904621","zp":"3d3425336a5d645d5e09199eabe0b9d5af817bbd35671a5cd42974483cd8c772","client_ip_address":"123.123.123.123","external_id":"b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10"},"custom_data":{"num_items":0,"event_id":"event-id"}}]}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://tr.snapchat.com/v3/pixel-id/events?access_token=access-token",
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
        ['missing pixel id', { oauth: { access_token: 'access-token' } }],
        ['missing access token', { pixelId: 'pixel-id' }],
    ])('handles %s', async (_, settings) => {
        const response = await tester.invokeMapping('Order Completed', settings, createAdDestinationPayload())

        expect(response.error).toMatchInlineSnapshot(`"Pixel ID and access token are required"`)
        expect(response.finished).toEqual(true)
    })
})

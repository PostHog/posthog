import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester, createAdDestinationPayload } from '../../test/test-helpers'
import { template } from './meta.template'

jest.setTimeout(2 * 60 * 1000)
describe('meta ads template', () => {
    const tester = new TemplateTester(template)
    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })
    it('builds a single-product ViewContent payload', async () => {
        const response = await tester.invokeMapping(
            'Product Viewed',
            { accessToken: 'access-token', pixelId: 'pixel-id' },
            createAdDestinationPayload({
                event: {
                    properties: {
                        sku: '43431-18',
                        category: 'merch',
                        name: 'Tactical black t-shirt',
                        price: 30,
                        quantity: 1,
                        currency: 'usd',
                        value: 30,
                    },
                    event: 'Product Viewed',
                },
            })
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"ViewContent","event_id":"event-id","event_time":1735689600,"action_source":"website","user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566"},"custom_data":{"currency":"usd","value":30,"content_type":"product","content_ids":["43431-18"],"contents":[{"id":"43431-18","quantity":1,"item_price":30}],"content_name":"Tactical black t-shirt","content_category":"merch"}}],"access_token":"access-token"}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://graph.facebook.com/v25.0/pixel-id/events",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { events_received: 1 },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
    it('omits value and contents for a Product Viewed without a quantity', async () => {
        const response = await tester.invokeMapping(
            'Product Viewed',
            { accessToken: 'access-token', pixelId: 'pixel-id' },
            createAdDestinationPayload({
                event: {
                    properties: {
                        sku: '43431-18',
                        name: 'Tactical black t-shirt',
                        category: 'merch',
                    },
                    event: 'Product Viewed',
                },
            })
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{\"data\":[{\"event_name\":\"ViewContent\",\"event_id\":\"event-id\",\"event_time\":1735689600,\"action_source\":\"website\",\"user_data\":{\"em\":\"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3\",\"fn\":\"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6\",\"ln\":\"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566\"},\"custom_data\":{\"currency\":\"USD\",\"content_type\":\"product\",\"content_ids\":[\"43431-18\"],\"content_name\":\"Tactical black t-shirt\",\"content_category\":\"merch\"}}],\"access_token\":\"access-token\"}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://graph.facebook.com/v25.0/pixel-id/events",
            }
        `)
    })
    it('builds a multi-product Purchase payload', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            { accessToken: 'access-token', pixelId: 'pixel-id' },
            createAdDestinationPayload({
                event: {
                    properties: {
                        order_id: '3e94e72c0a7443e9b51155a3',
                        revenue: 90.0,
                        currency: 'USD',
                        products: [
                            { sku: '18499-12', price: 30, quantity: 1 },
                            { sku: '94839-23', price: 30, quantity: 2 },
                        ],
                    },
                },
            })
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"Purchase","event_id":"event-id","event_time":1735689600,"action_source":"website","user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566"},"custom_data":{"currency":"USD","value":90,"content_type":"product","content_ids":["18499-12","94839-23"],"contents":[{"id":"18499-12","quantity":1,"item_price":30},{"id":"94839-23","quantity":2,"item_price":30}],"num_items":3,"order_id":"3e94e72c0a7443e9b51155a3"}}],"access_token":"access-token"}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://graph.facebook.com/v25.0/pixel-id/events",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { events_received: 1 },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
    it('sends a PageView with an empty custom_data', async () => {
        const response = await tester.invokeMapping(
            'Page Viewed',
            { accessToken: 'access-token', pixelId: 'pixel-id' },
            createAdDestinationPayload({ event: { event: '$pageview', properties: {} } })
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"PageView","event_id":"event-id","event_time":1735689600,"action_source":"website","user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566"},"custom_data":{}}],"access_token":"access-token"}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://graph.facebook.com/v25.0/pixel-id/events",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { events_received: 1 },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
    describe('fbc click ID', () => {
        // The event is fixed at 2025-01-01T00:00:00Z, so a click stamped 89 days earlier is inside
        // Meta's 90-day window and one stamped 91 days earlier is outside it.
        const eventMs = DateTime.fromISO('2025-01-01T00:00:00Z').toMillis()
        const dayMs = 24 * 60 * 60 * 1000

        it.each([
            {
                name: 'sends the $fbc PostHog stamped when it saw the click',
                event: {},
                person: { $fbc: `fb.1.${eventMs - 89 * dayMs}.AbC_123-x` },
                expected: `fb.1.${eventMs - 89 * dayMs}.AbC_123-x`,
            },
            {
                name: 'drops a click Meta would reject as older than 90 days',
                event: {},
                person: { $fbc: `fb.1.${eventMs - 91 * dayMs}.AbC_123-x` },
                expected: undefined,
            },
            {
                name: 'prefers the fbc the site stores itself',
                event: {},
                person: { fbc: `fb.1.${eventMs}.site-owned`, $fbc: `fb.1.${eventMs}.AbC_123-x` },
                expected: `fb.1.${eventMs}.site-owned`,
            },
            {
                name: 'stamps an fbclid on this event with the event time',
                event: { fbclid: 'AbC_123-x' },
                person: {},
                expected: `fb.1.${eventMs}.AbC_123-x`,
            },
            {
                name: 'sends nothing for an fbclid of unknown age',
                event: {},
                person: { fbclid: 'AbC_123-x' },
                expected: undefined,
            },
            {
                name: 'does not redate a stale click the event still carries',
                event: { fbclid: 'AbC_123-x' },
                person: { $fbc: `fb.1.${eventMs - 91 * dayMs}.AbC_123-x` },
                expected: undefined,
            },
            {
                name: "keeps the appendix Meta's parameter builder adds",
                event: {},
                person: { fbc: `fb.1.${eventMs}.AbC_123-x.Bg` },
                expected: `fb.1.${eventMs}.AbC_123-x.Bg`,
            },
            {
                name: "keeps the parameter builder's longer appendix",
                event: {},
                person: { fbc: `fb.1.${eventMs}.AbC_123-x.AQYAAQAA` },
                expected: `fb.1.${eventMs}.AbC_123-x.AQYAAQAA`,
            },
            {
                name: 'drops a click stamped after the conversion',
                event: {},
                person: { $fbc: `fb.1.${eventMs + dayMs}.AbC_123-x` },
                expected: undefined,
            },
            {
                name: 'keeps a click stamped a moment after the event by a drifting clock',
                event: {},
                person: { $fbc: `fb.1.${eventMs + 1000}.AbC_123-x` },
                expected: `fb.1.${eventMs + 1000}.AbC_123-x`,
            },
            {
                name: 'sends the event when a person holds a non-string fbc',
                event: {},
                person: { fbc: 1735689600000 },
                expected: undefined,
            },
        ])('$name', async ({ event, person, expected }) => {
            const response = await tester.invokeMapping(
                'Page Viewed',
                { accessToken: 'access-token', pixelId: 'pixel-id' },
                createAdDestinationPayload({
                    event: { event: '$pageview', properties: event },
                    person: { properties: person },
                })
            )

            expect(response.error).toBeUndefined()
            const body = parseJSON((response.invocation.queueParameters as { body: string }).body)
            expect(body.data[0].user_data.fbc).toEqual(expected)
            // A candidate the template rejects must cost only the fbc field, never the whole send.
            expect(body.data[0].user_data.em).toBeDefined()
        })
    })

    it('surfaces error responses', async () => {
        const response = await tester.invokeMapping(
            'Order Completed',
            { accessToken: 'access-token', pixelId: 'pixel-id' },
            createAdDestinationPayload()
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: { message: 'Invalid parameter' } },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from graph.facebook.com (status 400): {'error': {'message': 'Invalid parameter'}}"`
        )
    })
    it.each([
        ['missing pixel id', { accessToken: 'access-token' }],
        ['missing access token', { pixelId: 'pixel-id' }],
    ])('rejects %s', async (_, settings) => {
        const response = await tester.invokeMapping('Order Completed', settings, createAdDestinationPayload())
        expect(response.error).toMatchInlineSnapshot(`"Pixel ID and access token are required"`)
        expect(response.finished).toEqual(true)
    })
})

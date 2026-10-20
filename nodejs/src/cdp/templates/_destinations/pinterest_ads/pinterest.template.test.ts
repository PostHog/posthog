import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester, createAdDestinationPayload } from '../../test/test-helpers'
import { template } from './pinterest.template'

jest.setTimeout(2 * 60 * 1000)

const settings = { adAccountId: 'ad-account-id', conversionToken: 'conversion-token' }
const sentRequest = (response: any): { url: string; body: string } => response.invocation.queueParameters
const sentBody = (response: any): string => sentRequest(response).body
const sentEvent = (response: any): any => parseJSON(sentBody(response)).data[0]

describe('pinterest template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('sends a product event with content fields and hashed user data', async () => {
        const response = await tester.invokeMapping(
            'Product viewed',
            settings,
            createAdDestinationPayload({
                event: {
                    event: 'Product Viewed',
                    properties: {
                        sku: '43431-18',
                        name: 'Trail shoe 🥾 "Pro"',
                        brand: 'Café Nørd',
                        category: 'Footwear',
                        price: 30.5,
                        quantity: 2,
                        currency: 'EUR',
                        $current_url: 'https://example.com/shoes?epik=abc',
                        $ip: '203.0.113.7',
                        $raw_user_agent: 'Mozilla/5.0 (Macintosh)',
                    },
                },
                person: {
                    properties: {
                        email: '  Example@PostHog.com ',
                        phone: '+1 (234) 567-890',
                        first_name: 'Zoë',
                        $geoip_city_name: 'St. Louis',
                        $geoip_country_code: 'US',
                        epik: 'epik-click-id',
                    },
                },
            })
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"view_content","action_source":"web","event_time":1735689600,"event_id":"event-id","user_data":{"em":["3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3"],"ph":["c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646"],"fn":["2752b88686847fa5c86f47b94ce652b7b3f22a91c37617d451a4db9afa431450"],"ln":["32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566"],"ct":["8ba24bdf99947996f3000259be455de791b06fcc0e802ce05031030df1ee8ea3"],"country":["79adb2a2fce5c6ba215fe5f27f532d4e7edbac4b6a5e09e1ef3a08084a904621"],"external_id":["b5400f5d931b20e0e905cc4a009a428ce3427b3110e3a2a1cfc7e6349beabc10"],"client_ip_address":"203.0.113.7","client_user_agent":"Mozilla/5.0 (Macintosh)","click_id":"epik-click-id"},"event_source_url":"https://example.com/shoes?epik=abc","custom_data":{"currency":"EUR","value":"30.5","content_ids":["43431-18"],"contents":[{"id":"43431-18","item_price":"30.5","quantity":2,"item_name":"Trail shoe 🥾 \\"Pro\\"","item_brand":"Café Nørd","item_category":"Footwear"}],"num_items":2,"content_name":"Trail shoe 🥾 \\"Pro\\"","content_brand":"Café Nørd","content_category":"Footwear"}}]}",
              "headers": {
                "Authorization": "Bearer conversion-token",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.pinterest.com/v5/ad_accounts/ad-account-id/events",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { num_events_received: 1, num_events_processed: 1, events: [{ status: 'processed' }] },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('sends a multi product order in test mode, keeping a value of 0', async () => {
        const response = await tester.invokeMapping(
            'Order completed',
            { ...settings, testMode: true },
            createAdDestinationPayload({
                event: {
                    properties: {
                        order_id: 'order-1',
                        value: 0,
                        products: [
                            { sku: '18499-12', price: 30, quantity: 1 },
                            { product_id: 101, price: 15 },
                            { sku: '', product_id: 'p-3' },
                            { name: 'no id' },
                        ],
                    },
                },
            })
        )

        expect(sentRequest(response).url).toEqual(
            'https://api.pinterest.com/v5/ad_accounts/ad-account-id/events?test=true'
        )

        expect(sentEvent(response)).toMatchObject({
            event_name: 'checkout',
            custom_data: {
                value: '0',
                order_id: 'order-1',
                content_ids: ['18499-12', '101', 'p-3'],
                contents: [
                    { id: '18499-12', item_price: '30', quantity: 1 },
                    { id: '101', item_price: '15' },
                    { id: 'p-3' },
                ],
                num_items: 4,
            },
        })
    })

    it.each([
        ['no email', { email: null }, ['client_ip_address', 'client_user_agent', 'external_id', 'fn', 'ln', 'ph']],
        ['an email list with a null in it', { email: [null, ''] }, ['client_ip_address', 'client_user_agent']],
    ])('sends by IP and user agent for a person with %s', async (_, personProperties, expectedKeys) => {
        const response = await tester.invokeMapping(
            'Order completed',
            settings,
            createAdDestinationPayload({
                event: { properties: { $ip: '203.0.113.7', $raw_user_agent: 'Mozilla/5.0' } },
                person: { properties: personProperties },
            })
        )

        expect(response.error).toBeUndefined()
        const event = sentEvent(response)
        expect(event.user_data.em).toBeUndefined()
        expect(Object.keys(event.user_data)).toEqual(expect.arrayContaining(expectedKeys))
        expect(event.custom_data).toBeUndefined()
        expect(sentBody(response)).not.toContain('undefined')
        expect(sentBody(response)).not.toContain('null')
    })

    it('does not hash a value twice', async () => {
        const hashed = '3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3'
        const response = await tester.invokeMapping(
            'Page viewed',
            settings,
            createAdDestinationPayload({ person: { properties: { email: hashed.toUpperCase() } } })
        )

        expect(sentEvent(response).user_data.em).toEqual([hashed])
    })

    it('skips a person Pinterest cannot match', async () => {
        const response = await tester.invokeMapping(
            'Order completed',
            settings,
            createAdDestinationPayload({
                event: { properties: { $raw_user_agent: 'Mozilla/5.0' } },
                person: { properties: { email: null } },
            })
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.logs.map((log) => log.message)).toContainEqual(
            'Skipping event: Pinterest needs an email (em), a mobile ad ID (hashed_maids), or both an IP address and a user agent.'
        )
    })

    it.each([
        [
            'an error status',
            { status: 401, body: { code: 2, message: 'Authentication failed.' } },
            "Error from api.pinterest.com (status 401): {'code': 2, 'message': 'Authentication failed.'}",
        ],
        [
            'a rejected event in a 200 response',
            {
                status: 200,
                body: {
                    num_events_received: 1,
                    num_events_processed: 0,
                    events: [{ status: 'failed', error_message: 'Invalid event_name: purchase.' }],
                },
            },
            'Pinterest rejected the event: Invalid event_name: purchase.',
        ],
    ])('fails on %s', async (_, fetchResult, expectedError) => {
        const response = await tester.invokeMapping('Order completed', settings, createAdDestinationPayload())

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, fetchResult)
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toEqual(expectedError)
    })

    it.each([
        ['missing ad account ID', { conversionToken: 'conversion-token' }],
        ['missing conversion token', { adAccountId: 'ad-account-id' }],
    ])('fails on %s', async (_, incompleteSettings) => {
        const response = await tester.invokeMapping('Order completed', incompleteSettings, createAdDestinationPayload())
        expect(response.error).toMatchInlineSnapshot(`"Ad account ID and conversion token are required"`)
        expect(response.finished).toEqual(true)
    })
})

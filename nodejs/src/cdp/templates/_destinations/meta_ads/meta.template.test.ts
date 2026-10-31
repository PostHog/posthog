import { createHash } from 'crypto'
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
              "body": "{"data":[{"event_name":"ViewContent","event_id":"event-id","event_time":1735689600,"action_source":"website","user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566"},"custom_data":{"currency":"usd","value":30,"content_type":"product","content_ids":["43431-18"],"contents":[{"id":"43431-18","quantity":1,"item_price":30}],"content_name":"Tactical black t-shirt","content_category":"merch"}}],"access_token":"access-token"}",
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
              "body": "{\"data\":[{\"event_name\":\"ViewContent\",\"event_id\":\"event-id\",\"event_time\":1735689600,\"action_source\":\"website\",\"user_data\":{\"em\":\"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3\",\"ph\":\"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646\",\"fn\":\"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6\",\"ln\":\"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566\"},\"custom_data\":{\"currency\":\"USD\",\"content_type\":\"product\",\"content_ids\":[\"43431-18\"],\"content_name\":\"Tactical black t-shirt\",\"content_category\":\"merch\"}}],\"access_token\":\"access-token\"}",
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
              "body": "{"data":[{"event_name":"Purchase","event_id":"event-id","event_time":1735689600,"action_source":"website","user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566"},"custom_data":{"currency":"USD","value":90,"content_type":"product","content_ids":["18499-12","94839-23"],"contents":[{"id":"18499-12","quantity":1,"item_price":30},{"id":"94839-23","quantity":2,"item_price":30}],"num_items":3,"order_id":"3e94e72c0a7443e9b51155a3"}}],"access_token":"access-token"}",
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
              "body": "{"data":[{"event_name":"PageView","event_id":"event-id","event_time":1735689600,"action_source":"website","user_data":{"em":"3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3","ph":"c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646","fn":"9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6","ln":"32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566"},"custom_data":{}}],"access_token":"access-token"}",
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

    it('sends the IP address and user agent of an anonymous visitor', async () => {
        const response = await tester.invokeMapping(
            'Page Viewed',
            { accessToken: 'access-token', pixelId: 'pixel-id' },
            createAdDestinationPayload({
                event: {
                    event: '$pageview',
                    properties: { $ip: '203.0.113.7', $raw_user_agent: 'Mozilla/5.0' },
                },
                person: { properties: { email: '', phone: '', first_name: '', last_name: '' } },
            })
        )
        expect(response.error).toBeUndefined()
        const body = parseJSON((response.invocation.queueParameters as any).body)
        expect(body.data[0].user_data).toEqual({
            client_ip_address: '203.0.113.7',
            client_user_agent: 'Mozilla/5.0',
        })
    })

    it('skips an event with no customer information left after normalization', async () => {
        const response = await tester.invokeMapping(
            'Page Viewed',
            { accessToken: 'access-token', pixelId: 'pixel-id' },
            createAdDestinationPayload({
                event: { event: '$pageview', properties: {} },
                person: { properties: { email: 'not-an-email', phone: '', first_name: '', last_name: '' } },
            })
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toMatchInlineSnapshot(`
            [
              "No customer information left after normalization. Skipping...",
            ]
        `)
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
                name: 'falls back to $fbc when the site-owned fbc is malformed',
                event: {},
                person: { fbc: 'not-a-click-id', $fbc: `fb.1.${eventMs - dayMs}.AbC_123-x` },
                expected: `fb.1.${eventMs - dayMs}.AbC_123-x`,
            },
            {
                name: 'falls back to $fbc when the site-owned fbc is stale',
                event: {},
                person: { fbc: `fb.1.${eventMs - 91 * dayMs}.old`, $fbc: `fb.1.${eventMs - dayMs}.AbC_123-x` },
                expected: `fb.1.${eventMs - dayMs}.AbC_123-x`,
            },
            {
                name: 'sends the newest valid click',
                event: {},
                person: { fbc: `fb.1.${eventMs - 10 * dayMs}.older`, $fbc: `fb.1.${eventMs - dayMs}.newer` },
                expected: `fb.1.${eventMs - dayMs}.newer`,
            },
            {
                name: 'prefers an fbc the event carries over the same click on the person',
                event: { fbc: `fb.1.${eventMs}.event-owned` },
                person: { fbc: `fb.1.${eventMs}.site-owned` },
                expected: `fb.1.${eventMs}.event-owned`,
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

    describe('fbp browser ID', () => {
        it.each([
            {
                name: 'sends the $fbp the SDK read from the pixel cookie',
                person: { $fbp: 'fb.1.1735689600000.1098115397' },
                expected: 'fb.1.1735689600000.1098115397',
            },
            {
                name: 'prefers the fbp the site stores itself',
                person: { fbp: 'fb.1.1735689600000.2222222222', $fbp: 'fb.1.1735689600000.1098115397' },
                expected: 'fb.1.1735689600000.2222222222',
            },
            {
                name: 'prefers the fbp the event carries',
                event: { $fbp: 'fb.1.1735689600000.3333333333' },
                person: { $fbp: 'fb.1.1735689600000.1098115397' },
                expected: 'fb.1.1735689600000.3333333333',
            },
            {
                name: 'skips a malformed fbp for a valid one behind it',
                event: { fbp: 'not-a-browser-id' },
                person: { $fbp: 'fb.1.1735689600000.1098115397' },
                expected: 'fb.1.1735689600000.1098115397',
            },
            {
                name: "keeps the appendix Meta's parameter builder adds",
                person: { $fbp: 'fb.1.1735689600000.1098115397.Bg' },
                expected: 'fb.1.1735689600000.1098115397.Bg',
            },
            {
                name: 'sends nothing when the person holds no fbp',
                person: {},
                expected: undefined,
            },
        ])(
            '$name',
            async ({
                event,
                person,
                expected,
            }: {
                event?: Record<string, unknown>
                person: Record<string, unknown>
                expected?: string
            }) => {
                const response = await tester.invokeMapping(
                    'Page Viewed',
                    { accessToken: 'access-token', pixelId: 'pixel-id' },
                    createAdDestinationPayload({
                        event: { event: '$pageview', properties: event ?? {} },
                        person: { properties: person },
                    })
                )

                expect(response.error).toBeUndefined()
                const body = parseJSON((response.invocation.queueParameters as { body: string }).body)
                expect(body.data[0].user_data.fbp).toEqual(expected)
            }
        )
    })

    describe('user data normalization', () => {
        const sha256 = (value: string): string => createHash('sha256').update(value).digest('hex')

        it.each([
            {
                name: 'trims and lowercases an email',
                person: { email: '  Example@PostHog.com ' },
                key: 'em',
                expected: sha256('example@posthog.com'),
            },
            {
                name: 'keeps only the digits of a phone number',
                person: { phone: '+1 (234) 567-890' },
                key: 'ph',
                expected: sha256('1234567890'),
            },
            {
                name: 'drops the leading zeros of a phone number',
                person: { phone: '0044 20 7946 0958' },
                key: 'ph',
                expected: sha256('442079460958'),
            },
            {
                name: 'hashes a phone number stored as a number',
                person: { phone: 1234567890 },
                key: 'ph',
                expected: sha256('1234567890'),
            },
            {
                name: 'removes punctuation from a first name',
                person: { first_name: ' Mary-Jane ' },
                key: 'fn',
                expected: sha256('maryjane'),
            },
            {
                name: 'removes punctuation from a last name',
                person: { last_name: "O'Brien" },
                key: 'ln',
                expected: sha256('obrien'),
            },
            {
                name: 'removes spaces from a city',
                person: { $geoip_city_name: 'San Francisco' },
                key: 'ct',
                expected: sha256('sanfrancisco'),
            },
            {
                name: 'lowercases a state code',
                person: { $geoip_subdivision_1_code: 'CA' },
                key: 'st',
                expected: sha256('ca'),
            },
            {
                name: 'keeps the first 5 digits of a US ZIP+4 code',
                person: { $geoip_postal_code: '94107-1234' },
                key: 'zp',
                expected: sha256('94107'),
            },
            {
                name: 'removes spaces from a postal code',
                person: { $geoip_postal_code: 'SW1A 1AA' },
                key: 'zp',
                expected: sha256('sw1a1aa'),
            },
            {
                name: 'lowercases a country code',
                person: { $geoip_country_code: ' US ' },
                key: 'country',
                expected: sha256('us'),
            },
            {
                name: 'keeps accented letters in a name',
                person: { first_name: 'José María' },
                key: 'fn',
                expected: sha256('josémaría'),
            },
            {
                name: 'keeps letters outside the Basic Multilingual Plane',
                person: { last_name: '𠀀田' },
                key: 'ln',
                expected: sha256('𠀀田'),
            },
            {
                name: 'keeps the first 5 digits of a 9-digit US ZIP code',
                person: { $geoip_postal_code: '941071234', $geoip_country_code: 'US' },
                key: 'zp',
                expected: sha256('94107'),
            },
            {
                name: 'drops a US ZIP code that is not 5 or 9 digits',
                person: { $geoip_postal_code: '9410', $geoip_country_code: 'US' },
                key: 'zp',
                expected: undefined,
            },
            {
                name: 'keeps a non-US postal code that looks like a ZIP+4 code',
                person: { $geoip_postal_code: '1000-001', $geoip_country_code: 'PT' },
                key: 'zp',
                expected: sha256('1000001'),
            },
            {
                name: 'sends nothing for a malformed email',
                person: { email: 'not an email' },
                key: 'em',
                expected: undefined,
            },
            {
                name: 'sends nothing for a phone number too short to be valid',
                person: { phone: '12345' },
                key: 'ph',
                expected: undefined,
            },
            {
                name: 'sends nothing for a country that is not a 2-letter code',
                person: { $geoip_country_code: 'United States' },
                key: 'country',
                expected: undefined,
            },
            {
                name: 'sends nothing for a phone number without digits',
                person: { phone: 'n/a' },
                key: 'ph',
                expected: undefined,
            },
            {
                name: 'sends nothing for a missing field',
                person: { phone: null },
                key: 'ph',
                expected: undefined,
            },
            {
                name: 'trims tabs and line breaks from an email before hashing',
                person: { email: '\tAlice@example.com\n' },
                key: 'em',
                expected: sha256('alice@example.com'),
            },
        ])('$name', async ({ person, key, expected }) => {
            const response = await tester.invokeMapping(
                'Page Viewed',
                { accessToken: 'access-token', pixelId: 'pixel-id' },
                createAdDestinationPayload({
                    event: { event: '$pageview', properties: {} },
                    person: { properties: person },
                })
            )

            expect(response.error).toBeUndefined()
            const body = parseJSON((response.invocation.queueParameters as { body: string }).body)
            expect(body.data[0].user_data[key]).toEqual(expected)
        })

        it.each([
            {
                name: 'does not hash an already hashed value twice',
                userData: { em: sha256('example@posthog.com'), ph: sha256('1234567890').toUpperCase() },
                expected: { em: sha256('example@posthog.com'), ph: sha256('1234567890') },
            },
            {
                name: 'recognizes an already hashed email with a trailing line break',
                userData: { em: `${sha256('example@posthog.com')}\n` },
                expected: { em: sha256('example@posthog.com') },
            },
            {
                name: 'preserves a ParamBuilder hash and its case-sensitive appendix unchanged',
                userData: { em: `${sha256('example@posthog.com')}.AQQCAQMC`, fn: `${sha256('mary')}.AQQCAQMC` },
                expected: { em: `${sha256('example@posthog.com')}.AQQCAQMC`, fn: `${sha256('mary')}.AQQCAQMC` },
            },
            {
                name: 'lowercases only the digest of a ParamBuilder hash, keeping its appendix as is',
                userData: { em: `${sha256('example@posthog.com').toUpperCase()}.AQQCAQMC` },
                expected: { em: `${sha256('example@posthog.com')}.AQQCAQMC` },
            },
            {
                name: 'normalizes and hashes each value of a list',
                userData: { em: [' A@PostHog.com', 'b@posthog.com', ''] },
                expected: { em: [sha256('a@posthog.com'), sha256('b@posthog.com')] },
            },
            {
                name: 'caps a list at 50 items before hashing',
                userData: { em: Array.from({ length: 51 }, () => 'person@posthog.com') },
                expected: { em: Array.from({ length: 50 }, () => sha256('person@posthog.com')) },
            },
            {
                name: 'normalizes gender and date of birth',
                userData: { ge: 'Female', db: '1990-01-31' },
                expected: { ge: sha256('f'), db: sha256('19900131') },
            },
            {
                name: 'reorders a month-first date of birth into year-first order',
                userData: { db: '10/16/1997' },
                expected: { db: sha256('19971016') },
            },
            {
                name: 'sends nothing for an unknown gender or an incomplete date of birth',
                userData: { ge: 'other', db: '1990-01', client_user_agent: 'Mozilla/5.0' },
                expected: { client_user_agent: 'Mozilla/5.0' },
            },
            {
                name: 'drops a name too long to normalize safely',
                userData: { fn: 'a'.repeat(300), client_user_agent: 'Mozilla/5.0' },
                expected: { client_user_agent: 'Mozilla/5.0' },
            },
            {
                name: 'recognizes the US from a list-valued country when shortening a ZIP+4 code',
                userData: { zp: '941071234', country: ['US'] },
                expected: { zp: sha256('94107'), country: [sha256('us')] },
            },
            {
                name: 'recognizes the US from an already hashed country when shortening a ZIP+4 code',
                userData: { zp: '941071234', country: sha256('us') },
                expected: { zp: sha256('94107'), country: sha256('us') },
            },
            {
                name: 'leaves fields Meta does not want hashed as they are',
                userData: { external_id: 'User-123', client_user_agent: 'Mozilla/5.0' },
                expected: { external_id: 'User-123', client_user_agent: 'Mozilla/5.0' },
            },
        ])('$name', async ({ userData, expected }) => {
            const response = await tester.invokeMapping(
                'Page Viewed',
                { accessToken: 'access-token', pixelId: 'pixel-id', userData },
                createAdDestinationPayload({ event: { event: '$pageview', properties: {} } })
            )

            expect(response.error).toBeUndefined()
            const body = parseJSON((response.invocation.queueParameters as { body: string }).body)
            expect(body.data[0].user_data).toEqual(expected)
        })
    })

    describe('event source URL', () => {
        it.each([
            {
                name: 'sends the page URL',
                url: 'https://example.com/pricing?plan=pro#faq',
                expected: 'https://example.com/pricing?plan=pro#faq',
            },
            { name: 'trims the page URL', url: ' https://example.com/ ', expected: 'https://example.com/' },
            { name: 'leaves out a URL that is not http(s)', url: 'file:///Users/me/index.html', expected: undefined },
            { name: 'leaves out a value that is not a URL', url: 'Home screen', expected: undefined },
            { name: 'leaves out a URL with spaces', url: 'https://example.com/a page', expected: undefined },
        ])('$name', async ({ url, expected }) => {
            const response = await tester.invokeMapping(
                'Page Viewed',
                { accessToken: 'access-token', pixelId: 'pixel-id' },
                createAdDestinationPayload({ event: { event: '$pageview', properties: { $current_url: url } } })
            )

            expect(response.error).toBeUndefined()
            const body = parseJSON((response.invocation.queueParameters as { body: string }).body)
            expect(body.data[0].event_source_url).toEqual(expected)
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

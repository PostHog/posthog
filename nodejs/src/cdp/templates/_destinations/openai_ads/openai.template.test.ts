import { DateTime, Settings } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester, createAdDestinationPayload } from '../../test/test-helpers'
import { template } from './openai.template'

const EMAIL_SHA256 = '3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3'
const EXTERNAL_ID_SHA256 = 'c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646'
// The fixture phone +1234567890 hashes as the digits 1234567890, the same string as the fixture external ID
const PHONE_SHA256 = EXTERNAL_ID_SHA256
const FIRST_NAME_SHA256 = '9baf3a40312f39849f46dad1040f2f039f1cffa1238c41e9db675315cfad39b6'
const LAST_NAME_SHA256 = '32e83e92d45d71f69dcf9d214688f0375542108631b45d344e5df2eb91c11566'
// OpenAI's sample hash for +1 (415) 555-2671 in its Conversions API docs
const DOCS_PHONE_SHA256 = '758fbf68945f21c416814c539ab578876c8d98fb69e6da692def92cd52417fe0'
const NO_PHONE_OR_NAME = { phone: null, first_name: null, last_name: null }

const getBody = (response: { invocation: { queueParameters?: unknown } }): Record<string, any> =>
    parseJSON((response.invocation.queueParameters as { body: string }).body)

jest.setTimeout(60 * 1000)
describe('openai template', () => {
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
    it('sends a full standard conversion event', async () => {
        const response = await tester.invokeMapping(
            'Order created',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: {
                    properties: {
                        $current_url: 'https://posthog.com/checkout',
                        currency: 'USD',
                        value: '2599',
                    },
                },
            }),
            {
                amount: '{event.properties.value}',
                currency: '{event.properties.currency}',
            }
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchObject({
            url: 'https://bzr.openai.com/v1/events?pid=pixel-123',
            method: 'POST',
            headers: {
                Authorization: 'Bearer api-key',
                'Content-Type': 'application/json',
            },
        })
        expect(getBody(response)).toEqual({
            integration_source: 'posthog',
            events: [
                {
                    id: 'event-id',
                    type: 'order_created',
                    timestamp_ms: 1735689600000,
                    action_source: 'web',
                    source_url: 'https://posthog.com/checkout',
                    oppref: 'openai-id',
                    user: {
                        emails_sha256: [EMAIL_SHA256],
                        external_ids_sha256: [EXTERNAL_ID_SHA256],
                        phone_numbers_sha256: [PHONE_SHA256],
                        first_names_sha256: [FIRST_NAME_SHA256],
                        last_names_sha256: [LAST_NAME_SHA256],
                    },
                    data: {
                        type: 'contents',
                        amount: 2599,
                        currency: 'USD',
                    },
                },
            ],
        })
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })
    it('sends a custom event named after the PostHog event by default', async () => {
        const response = await tester.invokeMapping(
            'Custom',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: { properties: { $current_url: 'https://posthog.com/checkout' } },
            })
        )
        expect(response.error).toBeUndefined()
        const conversion = getBody(response).events[0]
        expect(conversion.type).toEqual('custom')
        // 'Order Completed' normalized to OpenAI's [a-z0-9_-] custom event name format
        expect(conversion.custom_event_name).toEqual('order-completed')
        expect(conversion.data).toEqual({ type: 'custom' })
    })
    // Each default mapping must send its OpenAI standard event type with the matching data shape
    it.each([
        ['Page viewed', 'page_viewed', 'contents'],
        ['Checkout started', 'checkout_started', 'contents'],
        ['Items added', 'items_added', 'contents'],
        ['Contents viewed', 'contents_viewed', 'contents'],
        ['Registration completed', 'registration_completed', 'customer_action'],
    ])('the %s mapping sends %s by default', async (mappingName, eventType, dataType) => {
        const response = await tester.invokeMapping(
            mappingName,
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: { properties: { $current_url: 'https://posthog.com/checkout' } },
            })
        )
        expect(response.error).toBeUndefined()
        const conversion = getBody(response).events[0]
        expect(conversion.type).toEqual(eventType)
        expect(conversion.action_source).toEqual('web')
        expect(conversion.data).toEqual({ type: dataType })
    })
    // Standard event types without a default mapping must still be usable via the choice input
    it.each([
        ['lead_created', 'customer_action'],
        ['trial_started', 'plan_enrollment'],
    ])('sends the %s event with the %s data shape', async (eventType, dataType) => {
        const response = await tester.invokeMapping(
            'Custom',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: { properties: { $current_url: 'https://posthog.com/checkout' } },
            }),
            { eventType }
        )
        expect(response.error).toBeUndefined()
        expect(getBody(response).events[0].data).toEqual({ type: dataType })
    })
    // Any one strong identifier is enough for OpenAI to attribute, so none of them may gate the send
    it.each([
        [
            'oppref',
            { email: null, external_id: null },
            (conversion: Record<string, any>) => {
                expect(conversion.oppref).toEqual('openai-id')
                expect(conversion.user).toBeUndefined()
            },
        ],
        [
            'obref',
            { oppref: null, email: null, external_id: null, $obref: 'obref-cookie' },
            (conversion: Record<string, any>) => {
                expect(conversion.user).toEqual({ obref: 'obref-cookie' })
            },
        ],
        [
            'email',
            { oppref: null, external_id: null },
            (conversion: Record<string, any>) => {
                expect(conversion.user).toEqual({ emails_sha256: [EMAIL_SHA256] })
            },
        ],
        [
            'externalId',
            { oppref: null, email: null },
            (conversion: Record<string, any>) => {
                expect(conversion.user).toEqual({ external_ids_sha256: [EXTERNAL_ID_SHA256] })
            },
        ],
        [
            'phone',
            { oppref: null, email: null, external_id: null, phone: '+1234567890' },
            (conversion: Record<string, any>) => {
                expect(conversion.user).toEqual({ phone_numbers_sha256: [PHONE_SHA256] })
            },
        ],
    ])('sends the conversion when only %s is available', async (_, personProperties, assertIdentifiers) => {
        const response = await tester.invokeMapping(
            'Custom',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: { properties: { $current_url: 'https://posthog.com/checkout' } },
                person: { properties: { ...NO_PHONE_OR_NAME, ...personProperties } },
            })
        )
        expect(response.error).toBeUndefined()
        assertIdentifiers(getBody(response).events[0])
    })
    // Person properties keep their JSON type, so a numeric customer ID must hash like its string form
    it.each([
        ['a numeric', 1234567890, EXTERNAL_ID_SHA256],
        ['a zero', 0, '5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9'],
        ['a string', ' 1234567890 ', EXTERNAL_ID_SHA256],
    ])('hashes %s external ID', async (_, externalId, expectedHash) => {
        const response = await tester.invokeMapping(
            'Custom',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: { properties: { $current_url: 'https://posthog.com/checkout' } },
                person: { properties: { ...NO_PHONE_OR_NAME, oppref: null, email: null, external_id: externalId } },
            })
        )
        expect(response.error).toBeUndefined()
        expect(getBody(response).events[0].user).toEqual({ external_ids_sha256: [expectedHash] })
    })
    it('skips when only weak identifiers are available', async () => {
        const response = await tester.invokeMapping(
            'Custom',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: {
                    properties: {
                        $current_url: 'https://posthog.com/checkout',
                        $ip: '203.0.113.1',
                        $raw_user_agent: 'Mozilla/5.0',
                    },
                },
                person: { properties: { oppref: null, email: null, external_id: null, phone: null } },
            })
        )
        expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toMatchInlineSnapshot(
            `
            [
              "No \`oppref\`, \`obref\`, \`email\`, \`externalId\` or \`phone\` to identify the user with. Skipping...",
            ]
        `
        )
        expect(response.finished).toEqual(true)
    })
    it.each([
        ['formatted phone', { phone: '+1 (415) 555-2671' }, { phone_numbers_sha256: [DOCS_PHONE_SHA256] }],
        [
            'phone with 00 prefix',
            { phone: '0044 20 7946 0000' },
            { phone_numbers_sha256: ['38e62b3e091778f9214de3aa00ae498aa4b78433d73dec5977eb2ec1c8be4a69'] },
        ],
        [
            'phone with Unicode spaces',
            { phone: '+1\u00a0415\u202f555\u20092671' },
            { phone_numbers_sha256: [DOCS_PHONE_SHA256] },
        ],
        ['phone without a country code', { phone: '415 555 2671' }, {}],
        [
            'pre-hashed phone',
            { phone: '758FBF68945F21C416814C539AB578876C8D98FB69E6DA692DEF92CD52417FE0' },
            { phone_numbers_sha256: [DOCS_PHONE_SHA256] },
        ],
        [
            'name with a space',
            { first_name: 'Mary Jane' },
            { first_names_sha256: ['f08f448a5e7a9dc3619bb7c129f6a7d5fc6af002cea17ad71dfdc1c68f4d4e0e'] },
        ],
        [
            'name with punctuation',
            { first_name: 'Anne-Marie', last_name: "O'Connor" },
            {
                first_names_sha256: ['67495eb5715de43c26f7c18b25cc7f62a7540236516bd59d5162a6f743598083'],
                last_names_sha256: ['7a0fbfdf40cbeb97429bdb88f512cecd27f0d44b7e57986ab578423bb61936ac'],
            },
        ],
        [
            'name with an accent',
            { last_name: 'José' },
            { last_names_sha256: ['d994e1d001886fe5b45b1267bd1fa2b752ac50742579bd3dad7b2a2aa0ed6866'] },
        ],
        ['name that is only punctuation', { first_name: '---' }, {}],
        [
            'name with a line break and Unicode spaces',
            { first_name: 'Mary\nJane', last_name: 'O\u2009Connor\u00a0' },
            {
                first_names_sha256: ['f08f448a5e7a9dc3619bb7c129f6a7d5fc6af002cea17ad71dfdc1c68f4d4e0e'],
                last_names_sha256: ['7a0fbfdf40cbeb97429bdb88f512cecd27f0d44b7e57986ab578423bb61936ac'],
            },
        ],
        [
            'hex-looking external ID',
            { external_id: 'A'.repeat(64) },
            { external_ids_sha256: ['d53eda7a637c99cc7fb566d96e9fa109bf15c478410a3f5eb4d4c4e26cd081f6'] },
        ],
        [
            'city longer than 128 characters',
            { $geoip_city_name: 'x'.repeat(129), $geoip_country_code: 'US' },
            { countries: ['US'] },
        ],
        [
            'location',
            {
                $geoip_city_name: ' San Francisco ',
                $geoip_subdivision_1_name: 'California',
                $geoip_postal_code: '94107',
                $geoip_country_code: 'us',
            },
            { cities: ['San Francisco'], regions: ['California'], postal_codes: ['94107'], countries: ['US'] },
        ],
        [
            'invalid postal code and country',
            { $geoip_postal_code: 'bad/postcode', $geoip_country_code: 'United States' },
            {},
        ],
    ])('normalizes %s', async (_, personProperties, expectedUser) => {
        const response = await tester.invokeMapping(
            'Custom',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: { properties: { $current_url: 'https://posthog.com/checkout' } },
                person: {
                    properties: { ...NO_PHONE_OR_NAME, email: null, external_id: null, ...personProperties },
                },
            })
        )
        expect(response.error).toBeUndefined()
        expect(getBody(response).events[0].user ?? {}).toEqual(expectedUser)
        expect(JSON.stringify(response.logs)).not.toContain('555')
    })
    it.each([
        [
            'the custom event name is missing',
            { customEventName: '' },
            '`customEventName` is required when the event type is `custom`',
        ],
        [
            'the custom event name is invalid after normalization',
            { customEventName: 'checkout: complete!' },
            '`customEventName` `checkout:-complete!` is invalid',
        ],
        [
            'the source URL is missing for a web event',
            { sourceUrl: '' },
            '`sourceUrl` is required when the action source is `web`',
        ],
        [
            'an app event is not sent from a mobile app',
            { eventType: 'app_installed' },
            '`actionSource` must be `mobile_app` when the event type is `app_installed`',
        ],
    ])('errors when %s', async (_, mappingOverrides, expectedError) => {
        const response = await tester.invokeMapping(
            'Custom',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload(),
            mappingOverrides
        )
        expect(response.finished).toEqual(true)
        expect(response.error).toContain(expectedError)
    })
    // The app mappings must default to the mobile_app action source, or they would throw out of the box
    it.each([
        ['App installed', 'app_installed'],
        ['App opened', 'app_opened'],
    ])('the %s mapping sends %s from a mobile app without a source URL', async (mappingName, eventType) => {
        const response = await tester.invokeMapping(
            mappingName,
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload()
        )
        expect(response.error).toBeUndefined()
        const conversion = getBody(response).events[0]
        expect(conversion.type).toEqual(eventType)
        expect(conversion.action_source).toEqual('mobile_app')
        expect(conversion.source_url).toBeUndefined()
        expect(conversion.data).toEqual({ type: 'customer_action' })
    })
    it('omits the amount when no currency is set, as OpenAI rejects one without the other', async () => {
        const response = await tester.invokeMapping(
            'Custom',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: { properties: { $current_url: 'https://posthog.com/checkout' } },
            }),
            { amount: '2599' }
        )
        expect(response.error).toBeUndefined()
        expect(getBody(response).events[0].data).toEqual({ type: 'custom' })
        expect(response.logs.some((log) => log.message.includes('`amount` is set but `currency` is missing'))).toBe(
            true
        )
    })
    it('handles error responses', async () => {
        const response = await tester.invokeMapping(
            'Custom',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: { properties: { $current_url: 'https://posthog.com/checkout' } },
            })
        )
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 401,
            body: { error: { code: 'unauthorized', message: 'Invalid API key' } },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toMatchInlineSnapshot(
            `"Error from bzr.openai.com (status 401): {'error': {'code': 'unauthorized', 'message': 'Invalid API key'}}"`
        )
    })
})

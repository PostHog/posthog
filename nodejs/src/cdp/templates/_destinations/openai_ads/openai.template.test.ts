import { DateTime, Settings } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester, createAdDestinationPayload } from '../../test/test-helpers'
import { template } from './openai.template'

const EMAIL_SHA256 = '3d4eee8538a4bbbe2ef7912f90ee494c1280f74dd7fd81232e58deb9cb9997e3'
const EXTERNAL_ID_SHA256 = 'c775e7b757ede630cd0aa1113bd102661ab38829ca52a6422ab782862f268646'

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
            events: [
                {
                    id: 'event-id',
                    type: 'order_created',
                    timestamp_ms: 1735689600000,
                    action_source: 'web',
                    source_url: 'https://posthog.com/checkout',
                    oppref: 'openai-id',
                    user: {
                        email_sha256: EMAIL_SHA256,
                        external_id_sha256: EXTERNAL_ID_SHA256,
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
                expect(conversion.user).toEqual({ email_sha256: EMAIL_SHA256 })
            },
        ],
        [
            'externalId',
            { oppref: null, email: null },
            (conversion: Record<string, any>) => {
                expect(conversion.user).toEqual({ external_id_sha256: EXTERNAL_ID_SHA256 })
            },
        ],
    ])('sends the conversion when only %s is available', async (_, personProperties, assertIdentifiers) => {
        const response = await tester.invokeMapping(
            'Custom',
            { pixelId: 'pixel-123', apiKey: 'api-key' },
            createAdDestinationPayload({
                event: { properties: { $current_url: 'https://posthog.com/checkout' } },
                person: { properties: personProperties },
            })
        )
        expect(response.error).toBeUndefined()
        assertIdentifiers(getBody(response).events[0])
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
                person: { properties: { oppref: null, email: null, external_id: null } },
            })
        )
        expect(response.logs.filter((log) => log.level === 'info').map((log) => log.message)).toMatchInlineSnapshot(
            `
            [
              "No \`oppref\`, \`obref\`, \`email\` or \`externalId\` to identify the user with. Skipping...",
            ]
        `
        )
        expect(response.finished).toEqual(true)
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

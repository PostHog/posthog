import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './customerio.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    site_id: 'SITE_ID',
    token: 'TOKEN',
    host: 'track.customer.io',
    action: 'automatic',
    include_all_properties: false,
    identifier_key: 'email',
    identifier_value: 'example@posthog.com',
    attributes: { name: 'example' },
    ...overrides,
})
describe('customerio template', () => {
    const tester = new TemplateTester(template)

    const parseBody = (response: Awaited<ReturnType<typeof tester.invoke>>): Record<string, any> => {
        return parseJSON((response.invocation.queueParameters as any).body)
    }

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })
    it('sends the entity request', async () => {
        const response = await tester.invoke(createInputs(), {
            event: { event: '$pageview', properties: { url: 'https://example.com' } },
        })
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"type":"person","action":"page","name":null,"identifiers":{"email":"example@posthog.com"},"attributes":{"name":"example"},"timestamp":1704067200}",
              "headers": {
                "Authorization": "Basic U0lURV9JRDpUT0tFTg==",
                "Content-Type": "application/json",
                "User-Agent": "PostHog Customer.io App",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://track.customer.io/api/v2/entity",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: { ok: true } })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    it.each([
        ['$identify', 'identify'],
        ['$set', 'identify'],
        ['$pageview', 'page'],
        ['$screen', 'screen'],
        ['$autocapture', 'event'],
        ['custom', 'event'],
    ])('maps %s to the %s action automatically', async (eventName, expectedAction) => {
        const response = await tester.invoke(createInputs(), {
            event: { event: eventName, properties: { url: 'https://example.com' } },
        })
        const body = parseBody(response)
        expect(body.action).toEqual(expectedAction)
    })
    it.each(['$identify', '$pageview', '$screen', '$autocapture', 'custom'])(
        'keeps the configured action for %s',
        async (eventName) => {
            const response = await tester.invoke(createInputs({ action: 'event' }), {
                event: { event: eventName, properties: { url: 'https://example.com' } },
            })
            const body = parseBody(response)
            expect(body.action).toEqual('event')
            expect(body.name).toEqual(eventName)
        }
    )
    it.each([
        ['omits event properties when the toggle is off', {}, { name: 'example' }],
        [
            'includes event properties when the toggle is on',
            { include_all_properties: true },
            { $current_url: 'https://example.com', name: 'example' },
        ],
        [
            'includes person properties for identify',
            { include_all_properties: true, action: 'identify' },
            { email: 'example@posthog.com', name: 'example' },
        ],
    ])('%s', async (_name, inputs, expected) => {
        const response = await tester.invoke(createInputs(inputs))
        const body = parseBody(response)
        expect(body.attributes).toEqual(expected)
    })
    it('truncates attribute values over 1000 characters', async () => {
        const response = await tester.invoke(createInputs({ include_all_properties: true }), {
            event: { event: '$pageview', properties: { url: 'https://example.com/' + '12345'.repeat(200) } },
        })
        const body = parseBody(response)
        expect(body.attributes.url).toHaveLength(1000)
        expect(body.attributes.url.startsWith('https://example.com/12345')).toBe(true)
    })
    it('skips the request when the identifier value is empty', async () => {
        const response = await tester.invoke(createInputs({ identifier_key: 'email', identifier_value: '' }))
        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
        expect(response.logs.filter((l) => l.level === 'info').map((l) => l.message)).toContain(
            'No identifier set. Skipping as identifier is required.'
        )
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: 'error' },
        })
        expect(fetchResponse.error).toMatchInlineSnapshot(`"Error from customer.io api: 400: {'error': 'error'}"`)
    })
})

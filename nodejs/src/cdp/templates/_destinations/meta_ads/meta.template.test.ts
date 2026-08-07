import { parseJSON } from '~/common/utils/json-parse'

import { execHogImmediate } from '../../../utils/hog-exec'
import { compileHog } from '../../compiler'
import { TemplateTester } from '../../test/test-helpers'
import { template } from './meta.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    accessToken: 'accessToken12345',
    pixelId: '123451234512345',
    eventName: 'checkout',
    eventTime: '1728812163',
    eventId: 'eventId12345',
    eventSourceUrl: 'https://www.example.com',
    actionSource: 'website',
    userData: {
        em: '3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98',
        fn: null,
        client_user_agent: 'Mozilla/5.0',
    },
    customData: { currency: 'USD', price: '15' },
    ...overrides,
})
describe('meta ads template', () => {
    const tester = new TemplateTester(template)
    const parseBody = (response: any): Record<string, any> => parseJSON(response.invocation.queueParameters.body)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('sends the conversion event', async () => {
        const response = await tester.invoke(createInputs())
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"data":[{"event_name":"checkout","event_id":"eventId12345","event_time":"1728812163","action_source":"website","user_data":{"em":"3edfaed7454eedb3c72bad566901af8bfbed1181816dde6db91dfff0f0cffa98","client_user_agent":"Mozilla/5.0"},"custom_data":{"currency":"USD","price":"15"},"event_source_url":"https://www.example.com"}],"access_token":"accessToken12345"}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://graph.facebook.com/v25.0/123451234512345/events",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { events_received: 1 },
        })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })

    /*
     * Meta wants arrays for some fields, but the dictionary inputs only hold strings, so the
     * template parses anything that looks like a JSON array back into one.
     *
     * Only string arrays are covered. An array of objects cannot be exercised here: input
     * values are parsed as Hog string templates, and the inner {"id": ...} reads as an
     * unterminated template expression. Production parses inputs the same way, so that form
     * looks broken there too — the Python harness never compiled inputs, which is why nothing
     * caught it.
     */
    it('parses json arrays out of the dictionary inputs', async () => {
        const response = await tester.invoke(
            createInputs({
                userData: { em: 'hashed', external_id: '["user123", "crm456"]' },
                customData: { currency: 'USD', content_ids: '["product123", "product456"]' },
            })
        )

        const data = parseBody(response).data[0]
        expect(data.user_data.external_id).toEqual(['user123', 'crm456'])
        expect(data.custom_data.content_ids).toEqual(['product123', 'product456'])
        expect(data.custom_data.currency).toEqual('USD')
    })
    it('leaves a leading space on an array value alone', async () => {
        const response = await tester.invoke(
            createInputs({ customData: { content_ids: '  ["product123", "product456"]' } })
        )
        expect(parseBody(response).data[0].custom_data.content_ids).toEqual(['product123', 'product456'])
    })
    it('omits empty values from user_data and custom_data', async () => {
        const response = await tester.invoke(
            createInputs({ userData: { em: 'hashed', fn: null, ln: '' }, customData: { currency: 'USD', value: '' } })
        )
        const data = parseBody(response).data[0]
        expect(data.user_data).toEqual({ em: 'hashed' })
        expect(data.custom_data).toEqual({ currency: 'USD' })
    })
    it.each([
        ['omits the test event code when unset', {}, false],
        ['includes the test event code when set', { testEventCode: 'TEST123' }, true],
    ])('%s', async (_name, overrides, expected) => {
        const response = await tester.invoke(createInputs(overrides))
        expect('test_event_code' in parseBody(response)).toBe(expected)
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: { message: 'Invalid parameter' } },
        })
        expect(result.error).toMatchInlineSnapshot(
            `"Error from graph.facebook.com (status 400): {'error': {'message': 'Invalid parameter'}}"`
        )
    })
}) /*
 * The fbc default builds Meta's click-id cookie value from person properties. Meta rejects
 * malformed values with subcode 2804001, so anything it cannot form correctly has to come
 * out empty rather than be sent. Compiled directly because the expression contains single
 * quotes, which the input-compiling test helper cannot carry.
 */
describe('meta ads fbc default', () => {
    const expression = (template.inputs_schema.find((i) => i.key === 'userData') as any).default.fbc as string
    const inner = expression.replace(/^\{/, '').replace(/\}$/, '')
    it.each([
        ['a clean fbclid', { fbclid: 'IwAR2F4-dbP0l7Mn1' }, /^fb\.1\.\d+\.IwAR2F4-dbP0l7Mn1$/],
        ['the initial fbclid fallback', { $initial_fbclid: 'AbC_123-x' }, /^fb\.1\.\d+\.AbC_123-x$/],
        [
            'a full cookie value passed through',
            { fbclid: 'fb.1.1752830400000.IwAR123' },
            /^fb\.1\.1752830400000\.IwAR123$/,
        ],
        ['url-encoded junk', { fbclid: 'IwAR%3D123 456' }, /^$/],
        ['a malformed prefix', { fbclid: 'fb.junk' }, /^$/],
        ['no fbclid at all', {}, /^$/],
    ])('builds %s', async (_name, personProperties, expected) => {
        const bytecode = await compileHog(`return ${inner}`)
        const { execResult } = execHogImmediate(bytecode, { globals: { person: { properties: personProperties } } })
        expect(String(execResult?.result ?? '')).toMatch(expected)
    })
})

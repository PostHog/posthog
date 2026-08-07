import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './june.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    apiKey: 'abcdef123456',
    include_all_properties: false,
    properties: { name: 'Max AI', email: 'max@posthog.com' },
    ...overrides,
})
const FULL_EVENT = {
    event: '$pageview',
    uuid: '151234234',
    distinct_id: 'abc123',
    timestamp: '2024-10-24T23:03:50.941Z',
    properties: {
        $is_identified: true,
        $app_build: '1.0.0',
        $app_version: '2.0',
        $app_name: 'PostHog',
        utm_campaign: 'test1',
        utm_content: 'test2',
        utm_medium: 'test3',
        utm_source: 'test4',
        utm_term: 'test5',
        $device_id: 'test6',
        $device_manufacturer: 'test7',
        $device_model: 'test8',
        $os_name: 'test9',
        $os_version: 'test10',
        $device_type: 'test11',
        $ip: 'test12',
        $browser_language: 'test13',
        $os: 'test14',
        $referrer: 'test15',
        $screen_height: 'test16',
        $screen_width: 'test17',
        $geoip_time_zone: 'test18',
        $raw_user_agent: 'test19',
        $current_url: 'https://hedgebox.net/faq?billing',
        $pathname: '/faq',
        title: 'Hedgebox',
    },
}
describe('june template', () => {
    const tester = new TemplateTester(template)
    const parseBody = (response: any): Record<string, any> => parseJSON(response.invocation.queueParameters.body)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('maps the full event onto the june context', async () => {
        const response = await tester.invoke(createInputs(), { event: FULL_EVENT })
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"properties":{"url":"https://hedgebox.net/faq?billing","path":"/faq","title":"Hedgebox","referrer":"test15","search":"?billing"},"traits":{"name":"Max AI","email":"max@posthog.com"},"timestamp":"2024-10-24T23:03:50.941Z","context":{"app":{"build":"1.0.0","version":"2.0","name":"PostHog"},"campaign":{"name":"test1","content":"test2","medium":"test3","source":"test4","term":"test5"},"device":{"id":"test6","manufacturer":"test7","model":"test8","name":"test9","version":"test10","type":"test11"},"os":{"name":"test14","version":"test10"},"referrer":{"url":"test15"},"screen":{"height":"test16","width":"test17"},"ip":"test12","locale":"test13","timezone":"test18","userAgent":"test19"},"messageId":"151234234","userId":"abc123"}",
              "headers": {
                "Authorization": "Basic abcdef123456",
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.june.so/sdk/page",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, { status: 200, body: {} })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    }) /* The june endpoint is chosen by event name, so each mapping needs a case. */
    it.each([
        ['$identify', 'identify'],
        ['$set', 'identify'],
        ['$pageview', 'page'],
        ['$screen', 'page'],
        ['purchase', 'track'],
    ])('sends %s to the %s endpoint', async (eventName, endpoint) => {
        const response = await tester.invoke(createInputs(), { event: { event: eventName } })
        expect((response.invocation.queueParameters as any).url).toEqual(`https://api.june.so/sdk/${endpoint}`)
    })
    it('only sets event on track calls', async () => {
        const tracked = await tester.invoke(createInputs(), { event: { event: 'purchase' } })
        const paged = await tester.invoke(createInputs(), { event: { event: '$pageview' } })
        expect(parseBody(tracked).event).toEqual('purchase')
        expect(parseBody(paged).event).toBeUndefined()
    }) /* Identified users are keyed by userId, anonymous ones by anonymousId. */
    it.each([
        [true, { userId: 'distinct-id', anonymousId: 'anon-1' }],
        [false, { userId: undefined, anonymousId: 'distinct-id' }],
    ])('keys the payload by identification state %s', async (isIdentified, expected) => {
        const response = await tester.invoke(createInputs(), {
            event: { properties: { $is_identified: isIdentified, $anon_distinct_id: 'anon-1' } },
        })
        const body = parseBody(response)
        expect(body.userId).toEqual(expected.userId)
        expect(body.anonymousId).toEqual(expected.anonymousId)
    })
    it('pulls the query string into properties.search', async () => {
        const response = await tester.invoke(createInputs(), {
            event: { properties: { $current_url: 'https://hedgebox.net/faq?billing' } },
        })
        expect(parseBody(response).properties.search).toEqual('?billing')
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, { status: 401, body: { error: 'nope' } })
        expect(result.error).toMatchInlineSnapshot(`"Error from api.june.so (status 401): {'error': 'nope'}"`)
    })
})

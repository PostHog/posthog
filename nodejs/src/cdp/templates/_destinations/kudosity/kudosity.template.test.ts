import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './kudosity.template'

const createInputs = (overrides: Record<string, any> = {}): Record<string, any> => ({
    api_key: 'test_api_key_123',
    sender: 'Alerts',
    recipient: '+15555551234',
    message: 'Alert: API Error Rate is 156 (threshold: 100)',
    track_links: false,
    debug: false,
    ...overrides,
})
describe('kudosity template', () => {
    const tester = new TemplateTester(template)
    const parseBody = (response: any): Record<string, any> => parseJSON(response.invocation.queueParameters.body)
    beforeEach(async () => {
        await tester.beforeEach()
    })
    it('sends the sms', async () => {
        const response = await tester.invoke(createInputs({ message_ref: 'alert_alert-123' }))
        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"message":"Alert: API Error Rate is 156 (threshold: 100)","sender":"Alerts","recipient":"+15555551234","message_ref":"alert_alert-123"}",
              "headers": {
                "Content-Type": "application/json",
                "x-api-key": "test_api_key_123",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://api.transmitmessage.com/v2/sms",
            }
        `)
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { id: 'msg-1' },
        })
        expect(fetchResponse.error).toBeUndefined()
        expect(fetchResponse.finished).toBe(true)
    })
    it.each(['recipient', 'message'])('skips the request when %s is empty', async (field) => {
        const response = await tester.invoke(createInputs({ [field]: '' }))
        expect(response.finished).toBe(true)
        expect(response.invocation.queueParameters).toBeUndefined()
    })

    /*
     * Both optional fields are omitted rather than sent empty or false. message_ref is
     * cleared explicitly, since the harness applies its schema default otherwise.
     */
    it('omits message_ref and track_links when unset', async () => {
        const response = await tester.invoke(createInputs({ message_ref: '' }))
        const body = parseBody(response)
        expect(body.message_ref).toBeUndefined()
        expect(body.track_links).toBeUndefined()
    })
    it('includes track_links when enabled', async () => {
        const response = await tester.invoke(createInputs({ track_links: true }))
        expect(parseBody(response).track_links).toBe(true)
    })
    it('errors on a non-2xx response', async () => {
        const response = await tester.invoke(createInputs())
        const result = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { error: 'invalid recipient' },
        })
        expect(result.error).toMatchInlineSnapshot(
            `"Error from Kudosity API (status 400): {'error': 'invalid recipient'}"`
        )
    })
})

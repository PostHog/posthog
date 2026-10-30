import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './textkit.template'

describe('textkit template', () => {
    const tester = new TemplateTester(template)
    const globals = { person: { properties: { phone: '+14155550132' } } }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should send the SMS with only the required fields', async () => {
        const response = await tester.invoke({ api_key: 'ssms_sk_test' }, globals)

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)

        const queueParams = response.invocation.queueParameters as {
            url: string
            method: string
            headers: Record<string, string>
            body: string
        }
        expect(queueParams.url).toBe('https://api.jointextkit.com/v1/messages')
        expect(queueParams.method).toBe('POST')
        expect(queueParams.headers.Authorization).toBe('Bearer ssms_sk_test')
        expect(queueParams.headers['Idempotency-Key']).toMatch(/^[0-9a-f]{64}$/)
        expect(parseJSON(queueParams.body)).toEqual({
            to: '+14155550132',
            body: 'PostHog event event-name was triggered',
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 201,
            body: { id: 'msg_1', status: 'sent' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('should send the from number when it is set', async () => {
        const response = await tester.invoke({ api_key: 'ssms_sk_test', from_number: 'pool_123' }, globals)

        expect(parseJSON((response.invocation.queueParameters as { body: string }).body)).toEqual({
            to: '+14155550132',
            from: 'pool_123',
            body: 'PostHog event event-name was triggered',
        })
    })

    it('should use a different idempotency key for a different message on the same event', async () => {
        const key = async (message: string): Promise<string> => {
            const response = await tester.invoke({ api_key: 'ssms_sk_test', message }, globals)
            return (response.invocation.queueParameters as { headers: Record<string, string> }).headers[
                'Idempotency-Key'
            ]
        }

        expect(await key('First step')).not.toEqual(await key('Second step'))
        expect(await key('First step')).toEqual(await key('First step'))
    })

    it('should treat a message held for later as sent', async () => {
        const response = await tester.invoke({ api_key: 'ssms_sk_test' }, globals)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 202,
            body: { id: 'sm_1', status: 'scheduled' },
        })

        expect(fetchResponse.error).toBeUndefined()
    })

    it.each([
        { name: 'the phone number is empty', inputs: { to_number: '' }, error: /Recipient phone number/ },
        { name: 'the API key is empty', inputs: { api_key: '' }, error: /API key/ },
        { name: 'the message is empty', inputs: { message: '' }, error: /Message is required/ },
    ])('should error when $name', async ({ inputs, error }) => {
        const response = await tester.invoke({ api_key: 'ssms_sk_test', ...inputs }, globals)

        expect(response.error).toMatch(error)
    })

    it('should surface the error TextKit returns', async () => {
        const response = await tester.invoke({ api_key: 'ssms_sk_test' }, globals)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 403,
            body: { error: { code: 'recipient_opted_out', message: 'This number opted out.' } },
        })

        expect(fetchResponse.error).toMatch('Failed to send SMS via TextKit: 403: This number opted out.')
    })
})

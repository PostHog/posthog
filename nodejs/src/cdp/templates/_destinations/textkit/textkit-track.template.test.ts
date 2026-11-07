import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './textkit-track.template'

describe('textkit event template', () => {
    const tester = new TemplateTester(template)
    const globals = {
        event: { event: 'trial_started', uuid: 'event-uuid', distinct_id: 'user-1' },
        person: { properties: { phone: '+14155550132' } },
    }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('should send the event with the default inputs', async () => {
        const response = await tester.invoke({ api_key: 'ssms_sk_test' }, globals)

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)

        const queueParams = response.invocation.queueParameters as {
            url: string
            method: string
            headers: Record<string, string>
            body: string
        }
        expect(queueParams.url).toBe('https://api.jointextkit.com/v1/track')
        expect(queueParams.method).toBe('POST')
        expect(queueParams.headers.Authorization).toBe('Bearer ssms_sk_test')
        expect(queueParams.headers['Idempotency-Key']).toBe('event-uuid')
        expect(parseJSON(queueParams.body)).toEqual({
            event: 'trial_started',
            user_id: 'user-1',
            phone: '+14155550132',
            properties: { url: 'https://example.com' },
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 201,
            body: { id: 'evt_1' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it.each([
        ['$pageview', 'pageview'],
        ['Signed up', 'Signed_up'],
    ])('should send %s as %s', async (name, expected) => {
        const response = await tester.invoke(
            { api_key: 'ssms_sk_test' },
            { ...globals, event: { ...globals.event, event: name } }
        )

        expect(parseJSON((response.invocation.queueParameters as { body: string }).body).event).toBe(expected)
    })

    it('should leave out a phone number the person does not have', async () => {
        const response = await tester.invoke({ api_key: 'ssms_sk_test' }, { event: globals.event })

        const body = parseJSON((response.invocation.queueParameters as { body: string }).body)
        expect(body.user_id).toBe('user-1')
        expect(body).not.toHaveProperty('phone')
    })

    it('should error when neither a user ID nor a phone number is set', async () => {
        const response = await tester.invoke({ api_key: 'ssms_sk_test', user_id: '', phone: '' }, globals)

        expect(response.error).toMatch(/User ID or phone number is required/)
    })

    it('should surface the error TextKit returns', async () => {
        const response = await tester.invoke({ api_key: 'ssms_sk_test' }, globals)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 401,
            body: { error: { code: 'invalid_api_key', message: 'That key is not valid.' } },
        })

        expect(fetchResponse.error).toMatch('Failed to send event to TextKit: 401: That key is not valid.')
    })
})

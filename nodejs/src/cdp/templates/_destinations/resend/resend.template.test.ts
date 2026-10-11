import { CyclotronJobInvocationResult } from '~/cdp/types'
import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './resend.template'

describe('resend template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const inputs = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
        api_key: 're_test_key',
        from: 'Alerts <alerts@example.com>',
        to: 'one@example.com, two@example.com,',
        subject: 'New issue: TypeError',
        text: 'Cannot read properties of undefined',
        html: '',
        reply_to: '',
        ...overrides,
    })

    const sentBody = (response: CyclotronJobInvocationResult): Record<string, any> => {
        const params = response.invocation.queueParameters as { body: string }
        return parseJSON(params.body)
    }

    it('sends the email to every listed recipient', async () => {
        const response = await tester.invoke(inputs())

        expect(response.error).toBeUndefined()
        expect(response.invocation.queueParameters).toMatchObject({
            type: 'fetch',
            url: 'https://api.resend.com/emails',
            method: 'POST',
            headers: { Authorization: 'Bearer re_test_key', 'Content-Type': 'application/json' },
        })
        expect(sentBody(response)).toEqual({
            from: 'Alerts <alerts@example.com>',
            to: ['one@example.com', 'two@example.com'],
            subject: 'New issue: TypeError',
            text: 'Cannot read properties of undefined',
        })

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { id: 'email-id' },
        })
        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    it('includes the optional HTML body and reply-to address', async () => {
        const response = await tester.invoke(inputs({ html: '<p>Hello</p>', reply_to: 'team@example.com' }))

        expect(sentBody(response)).toMatchObject({ html: '<p>Hello</p>', reply_to: 'team@example.com' })
    })

    it.each([
        ['no recipient', { to: ' , ' }, 'Add at least one recipient email address.'],
        ['no body', { text: '', html: '' }, 'Add a plain text or HTML body.'],
    ])('fails without a request when there is %s', async (_name, overrides, error) => {
        const response = await tester.invoke(inputs(overrides))

        expect(response.error).toContain(error)
        expect(response.invocation.queueParameters).toBeFalsy()
    })

    it('fails when Resend rejects the email', async () => {
        const response = await tester.invoke(inputs())
        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 403,
            body: { message: 'The domain is not verified' },
        })

        expect(fetchResponse.error).toContain('Resend rejected the email: 403')
    })
})

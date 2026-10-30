import { createHmac } from 'node:crypto'

import { CyclotronInvocationQueueParametersFetchType } from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './t3-code.template'

describe('t3 code template', () => {
    const tester = new TemplateTester(template)

    const webhookUrl = 'https://relay.example.com/v1/hooks/endpoint-key/hook-id/url-token'
    const signingSecret = 'test-signing-secret'
    const inputs = {
        webhook_url: webhookUrl,
        instructions: 'Find out why {person.properties.email} saw a checkout error',
        payload: { event: '{event}', person: '{person}' },
    }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    const stagedRequest = async (
        stepInputs: Record<string, any>
    ): Promise<{
        invocation: Awaited<ReturnType<TemplateTester['invoke']>>['invocation']
        params: CyclotronInvocationQueueParametersFetchType
    }> => {
        const response = await tester.invoke(stepInputs)
        expect(response.error).toBeUndefined()
        return { invocation: response.invocation, params: response.invocation.queueParameters as any }
    }

    it('posts the instructions, event and person to the webhook URL', async () => {
        const { params } = await stagedRequest(inputs)

        expect(params).toMatchObject({ type: 'fetch', method: 'POST', url: webhookUrl })
        expect(params.headers).toMatchObject({
            'Content-Type': 'application/json',
            'x-posthog-delivery-id': expect.stringMatching(/^[0-9a-f-]{36}$/),
        })
        expect(params.headers).not.toHaveProperty('x-hub-signature-256')
        expect(parseJSON(params.body!)).toMatchObject({
            instructions: 'Find out why example@posthog.com saw a checkout error',
            event: { event: 'event-name', distinct_id: 'distinct-id' },
            person: { id: 'person-id', properties: { email: 'example@posthog.com' } },
        })
    })

    it('signs the exact body it sends the way the T3 Code signature check expects', async () => {
        const { params } = await stagedRequest({ ...inputs, signing_secret: signingSecret })

        const expectedSignature = createHmac('sha256', signingSecret).update(params.body!).digest('hex')
        expect(params.headers).toMatchObject({ 'x-hub-signature-256': `sha256=${expectedSignature}` })
        expect(JSON.stringify(params)).not.toContain(signingSecret)
    })

    it('returns the delivery id when T3 Code accepts the request', async () => {
        const { invocation } = await stagedRequest(inputs)

        const response = await tester.invokeFetchResponse(invocation, { status: 202, body: { deliveryId: 'd-1' } })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.execResult).toEqual({ deliveryId: 'd-1' })
    })

    it.each([
        [401, 'invalid_signature', 'T3 Code rejected the signature'],
        [404, 'hook_not_found', 'T3 Code has no task at this webhook URL'],
        [409, 'hook_disabled', 'The T3 Code task is turned off'],
        [410, 'delivery_too_old', 'T3 Code skipped the request because it was too old'],
        [413, 'body_too_large', 'The request is larger than the 1 MB T3 Code accepts'],
        [429, 'rate_limited', 'T3 Code is limiting requests to this task'],
        [500, 'internal_error', 'T3 Code could not start the task'],
    ])('fails a %s reply with a message that says what to fix', async (status, error, message) => {
        const { invocation } = await stagedRequest(inputs)

        const response = await tester.invokeFetchResponse(invocation, { status, body: { error } })

        expect(response.finished).toBe(true)
        expect(response.error).toContain(message)
    })
})

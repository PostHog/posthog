import {
    CyclotronInvocationQueueParametersFetchSchema,
    CyclotronInvocationQueueParametersFetchType,
} from '~/cdp/schema/cyclotron'
import { parseJSON } from '~/common/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './t3-code.template'

describe('t3 code template', () => {
    const tester = new TemplateTester(template)

    const webhookUrl = 'https://relay.example.com/v1/hooks/endpoint-key/hook-id/url-token'
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
        return {
            invocation: response.invocation,
            params: CyclotronInvocationQueueParametersFetchSchema.parse(response.invocation.queueParameters),
        }
    }

    it('posts the instructions, event and person to the webhook URL', async () => {
        const { params } = await stagedRequest(inputs)

        expect(params).toMatchObject({ type: 'fetch', method: 'POST', url: webhookUrl })
        expect(params.headers).toMatchObject({
            'Content-Type': 'application/json',
            'webhook-id': expect.stringMatching(/^[0-9a-f-]{36}$/),
        })
        expect(params.hmac_sha256).toBeUndefined()
        expect(parseJSON(params.body!)).toMatchObject({
            instructions: 'Find out why example@posthog.com saw a checkout error',
            event: { event: 'event-name', distinct_id: 'distinct-id' },
            person: { id: 'person-id', properties: { email: 'example@posthog.com' } },
        })
    })

    it('sends the event and person when a workflow saved through the API leaves Data out', async () => {
        const { params } = await stagedRequest({ ...inputs, payload: null })

        expect(parseJSON(params.body!)).toMatchObject({
            event: { event: 'event-name' },
            person: { properties: { email: 'example@posthog.com' } },
        })
    })

    it.each([
        ['a list', ['first', 'second']],
        ['a string', 'checkout failed'],
    ])('sends data that is %s next to the instructions', async (_, data) => {
        const { params } = await stagedRequest({ ...inputs, payload: data })

        expect(parseJSON(params.body!)).toEqual({
            data,
            instructions: 'Find out why example@posthog.com saw a checkout error',
        })
    })

    it('has the fetch sign the body with a reference to the signing secret, not the secret', async () => {
        const { params } = await stagedRequest({ ...inputs, signing_secret: 'test-signing-secret' })

        expect(params.hmac_sha256).toEqual({ secret_input: 'signing_secret', webhook_id: expect.any(String) })
        expect(JSON.stringify(params)).not.toContain('test-signing-secret')
    })

    it('returns the delivery id when T3 Code accepts the request', async () => {
        const { invocation } = await stagedRequest(inputs)

        const response = await tester.invokeFetchResponse(invocation, { status: 202, body: { deliveryId: 'd-1' } })

        expect(response.error).toBeUndefined()
        expect(response.finished).toBe(true)
        expect(response.execResult).toEqual({ deliveryId: 'd-1' })
    })

    it('fails with the status and error T3 Code replied with', async () => {
        const { invocation } = await stagedRequest(inputs)

        const response = await tester.invokeFetchResponse(invocation, { status: 409, body: { error: 'hook_disabled' } })

        expect(response.finished).toBe(true)
        expect(response.error).toContain('status 409')
        expect(response.error).toContain('hook_disabled')
    })
})

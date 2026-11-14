import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './webhook.template'

describe('webhook template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                url: 'https://example.com?v={event.properties.$lib_version}',
                debug: false,
            },
            {
                event: {
                    properties: {
                        $lib_version: '1.0.0',
                    },
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(false)
        expect(response.invocation.queueParameters).toMatchInlineSnapshot(`
            {
              "body": "{"event":{"uuid":"event-id","event":"event-name","distinct_id":"distinct-id","properties":{"$lib_version":"1.0.0"},"timestamp":"2024-01-01T00:00:00Z","elements_chain":"","url":"https://us.posthog.com/projects/1/events/1234"},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}}",
              "headers": {
                "Content-Type": "application/json",
              },
              "method": "POST",
              "type": "fetch",
              "url": "https://example.com?v=1.0.0",
            }
        `)

        const fetchResponse = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { message: 'Hello, world!' },
        })

        expect(fetchResponse.finished).toBe(true)
        expect(fetchResponse.error).toBeUndefined()
    })

    // The queue payload is stored as plaintext JSON, so the template must pass
    // an input-key reference for the executor to resolve at fetch time, never
    // the secret itself.
    it('passes a signing secret reference, not the secret, to the fetch queue', async () => {
        const response = await tester.invoke({
            url: 'https://example.com',
            signing_secret: 'whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw',
        })

        expect(response.error).toBeUndefined()
        const params = response.invocation.queueParameters as any
        expect(params.standard_webhooks).toEqual({
            secret_input: 'signing_secret',
            webhook_id: expect.any(String),
        })
        expect(JSON.stringify(params)).not.toContain('MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw')
    })

    it('passes a secret headers reference, not the values, to the fetch queue', async () => {
        const response = await tester.invoke({
            url: 'https://example.com',
            headers: { 'Content-Type': 'application/json' },
            secret_headers: { Authorization: 'Bearer sk_test_token' },
            debug: true,
        })

        expect(response.error).toBeUndefined()
        const params = response.invocation.queueParameters as any
        expect(params.secret_headers_input).toEqual('secret_headers')
        expect(params.headers).toEqual({ 'Content-Type': 'application/json' })
        expect(JSON.stringify(params)).not.toContain('Authorization')
        expect(response.logs.map((l) => l.message).join('\n')).not.toContain('Authorization')
    })

    it('should log details of given', async () => {
        let response = await tester.invoke({
            url: 'https://example.com?v={event.properties.$lib_version}',
            debug: true,
        })

        expect(response.error).toBeUndefined()
        expect(response.logs.filter((l) => l.level === 'info').map((l) => l.message)).toMatchInlineSnapshot(`
            [
              "Request, https://example.com?v=, {"headers":{"Content-Type":"application/json"},"body":{"event":{"uuid":"event-id","event":"event-name","distinct_id":"distinct-id","properties":{"$current_url":"https://example.com"},"timestamp":"2024-01-01T00:00:00Z","elements_chain":"","url":"https://us.posthog.com/projects/1/events/1234"},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}},"method":"POST"}",
            ]
        `)

        response = await tester.invokeFetchResponse(response.invocation, {
            status: 200,
            body: { message: 'Hello, world!' },
        })

        expect(response.error).toBeUndefined()
        expect(response.logs.filter((l) => l.level === 'info').map((l) => l.message)).toMatchInlineSnapshot(`
            [
              "Response, 200, {"message":"Hello, world!"}",
            ]
        `)
    })

    it('should throw an error if the webhook fails', async () => {
        let response = await tester.invoke({
            url: 'https://example.com?v={event.properties.$lib_version}',
            debug: true,
        })

        response = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { message: 'Bad Request' },
        })

        expect(response.error).toMatchInlineSnapshot(`"Webhook failed with status 400: {'message': 'Bad Request'}"`)
        expect(response.logs.filter((l) => l.level === 'error').map((l) => l.message)).toMatchInlineSnapshot(`
            [
              "Error executing function on event event-id: Error('Webhook failed with status 400: {\\'message\\': \\'Bad Request\\'}')",
            ]
        `)
    })

    describe('with continue_on_error', () => {
        const respond = async (response: { status: number; body: unknown; error?: string }) => {
            const invocation = (await tester.invoke({ url: 'https://example.com', continue_on_error: true })).invocation
            invocation.state.vmState!.stack.push({ ...response, duration_ms: 12 })
            return tester.resumeInvocation(invocation)
        }

        it('makes one attempt that cannot fail the step, with the timeout it was given', async () => {
            const response = await tester.invoke({
                url: 'https://example.com',
                method: 'HEAD',
                continue_on_error: true,
                timeout_ms: 2500,
            })

            expect(response.invocation.queueParameters).toMatchObject({
                method: 'HEAD',
                fail_on_error: false,
                max_tries: 1,
                timeout_ms: 2500,
            })
        })

        it.each([
            [
                'an error status',
                { status: 503, body: 'down' },
                { status: 503, body: 'down', duration_ms: 12, error: null },
            ],
            [
                'no response',
                { status: 500, body: 'TypeError: fetch failed', error: 'TypeError: fetch failed' },
                { status: 0, body: null, duration_ms: 12, error: 'TypeError: fetch failed' },
            ],
            [
                'a long JSON body',
                { status: 200, body: { page: 'a'.repeat(2000) } },
                { status: 200, body: `{"page":"${'a'.repeat(991)}`, duration_ms: 12, error: null },
            ],
        ])('stores %s instead of failing', async (_name, fetchResponse, expected) => {
            const result = await respond(fetchResponse)

            expect(result.error).toBeUndefined()
            expect(result.finished).toBe(true)
            expect(result.execResult).toEqual(expected)
        })
    })
})

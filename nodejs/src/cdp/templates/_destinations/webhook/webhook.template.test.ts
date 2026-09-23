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

    // A workflow step branches on the response status, so a status the author accepts has to survive
    // as the step result instead of failing the step.
    it.each([
        ['an exact code', [404], 404],
        ['the 4xx wildcard', ['4xx'], 404],
        ['the 5xx wildcard in upper case', ['5XX'], 503],
    ])('returns the response status for a code listed as non-failure with %s', async (_, codes, status) => {
        let response = await tester.invoke({
            url: 'https://example.com',
            non_failure_status_codes: codes,
        })

        response = await tester.invokeFetchResponse(response.invocation, {
            status,
            body: { message: 'Not Found' },
        })

        expect(response.error).toBeUndefined()
        expect(response.execResult).toEqual({ status, body: { message: 'Not Found' } })
    })

    it.each([
        ['no codes are listed', {}],
        ['the status is not in the list', { non_failure_status_codes: [404, '5xx'] }],
    ])('should throw an error if the webhook fails and %s', async (_, extraInputs) => {
        let response = await tester.invoke({
            url: 'https://example.com?v={event.properties.$lib_version}',
            debug: true,
            ...extraInputs,
        })

        response = await tester.invokeFetchResponse(response.invocation, {
            status: 400,
            body: { message: 'Bad Request' },
        })

        expect(response.error).toEqual("Webhook failed with status 400: {'message': 'Bad Request'}")
        expect(response.logs.filter((l) => l.level === 'error').map((l) => l.message)).toEqual([
            "Error executing function on event event-id: Error('Webhook failed with status 400: {\\'message\\': \\'Bad Request\\'}')",
        ])
    })
})

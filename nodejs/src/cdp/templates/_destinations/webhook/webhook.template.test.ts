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
                "Accept": "application/json",
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
              "Request, https://example.com?v=, {"headers":{"Content-Type":"application/json","Accept":"application/json"},"body":{"event":{"uuid":"event-id","event":"event-name","distinct_id":"distinct-id","properties":{"$current_url":"https://example.com"},"timestamp":"2024-01-01T00:00:00Z","elements_chain":"","url":"https://us.posthog.com/projects/1/events/1234"},"person":{"id":"person-id","name":"person-name","properties":{"email":"example@posthog.com"},"url":"https://us.posthog.com/projects/1/persons/1234"}},"method":"POST"}",
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

    // A 3xx redirect is not followed, so it must fail like a 4xx/5xx instead of passing silently.
    it.each([
        [302, 'Found'],
        [400, 'Bad Request'],
        [500, 'Internal Server Error'],
    ])('should throw an error for a %s response', async (status, message) => {
        let response = await tester.invoke({
            url: 'https://example.com',
            debug: false,
        })

        response = await tester.invokeFetchResponse(response.invocation, {
            status,
            body: { message },
        })

        expect(response.error).toEqual(`Webhook failed with status ${status}: {'message': '${message}'}`)
    })
})

import { mockFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'
import { createHmac } from 'node:crypto'

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

    it.each([
        [undefined, 'standard_webhooks'],
        ['standard_webhooks', 'standard_webhooks'],
        ['hmac_sha256', 'hmac_sha256'],
    ] as const)(
        'signs the delivery as format %s names, keeping the secret out of the queue payload',
        async (signingFormat, signer) => {
            const secret = 'whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw'
            const standardWebhooksKey = Buffer.from('MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw', 'base64')

            const response = await tester.invoke({
                url: 'https://example.com',
                signing_secret: secret,
                signing_format: signingFormat,
            })
            expect(response.error).toBeUndefined()
            expect(JSON.stringify(response.invocation.queueParameters)).not.toContain(secret)

            const delivery = await tester.executeFetch(response.invocation)

            expect(delivery.error).toBeUndefined()
            const [url, { headers, body }] = mockFetch.mock.calls[0] as [string, any]
            expect(url).toBe('https://example.com')
            const standardWebhooksContent = `${headers['webhook-id']}.${headers['webhook-timestamp']}.${body}`
            expect({
                'webhook-signature': headers['webhook-signature'],
                'x-hub-signature-256': headers['x-hub-signature-256'],
            }).toEqual(
                signer === 'standard_webhooks'
                    ? {
                          'webhook-signature': `v1,${createHmac('sha256', standardWebhooksKey).update(standardWebhooksContent).digest('base64')}`,
                          'x-hub-signature-256': undefined,
                      }
                    : {
                          'webhook-signature': undefined,
                          'x-hub-signature-256': `sha256=${createHmac('sha256', secret).update(body).digest('hex')}`,
                      }
            )
        }
    )

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
})

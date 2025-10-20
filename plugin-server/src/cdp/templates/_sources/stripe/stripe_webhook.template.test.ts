import crypto from 'crypto'
import { DateTime } from 'luxon'

import { parseJSON } from '~/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import stripeWebhook from './__tests__/stripe-webhook.json'
import { template } from './stripe_webhook.template'

describe('stripe webhook template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                signing_secret: 'whsec_testsecret',
                include_all_properties: true,
            },
            {
                request: createStripeWebhook('whsec_testsecret'),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)

        expect(response.capturedPostHogEvents).toMatchObject([
            {
                distinct_id: 'cus_1234',
                event: 'stripe.invoice.payment_succeeded',
                properties: {},
                team_id: 1,
                timestamp: '2025-01-01T00:00:00.000Z',
            },
        ])

        expect(response.capturedPostHogEvents).toMatchSnapshot()
    })

    it('should not include all properties if include_all_properties is false', async () => {
        const response = await tester.invoke(
            {
                signing_secret: 'whsec_testsecret',
                include_all_properties: false,
            },
            {
                request: createStripeWebhook('whsec_testsecret'),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)

        expect(response.capturedPostHogEvents[0].properties).toMatchInlineSnapshot(`
            {
              "$hog_function_execution_count": 1,
            }
        `)
    })

    it('should include all properties except those overridden', async () => {
        const response = await tester.invoke(
            {
                signing_secret: 'whsec_testsecret',
                include_all_properties: true,
                properties: {
                    foo: 'bar',
                    account_name: '{request.body.data.object.account_name} - modified',
                },
            },
            {
                request: createStripeWebhook('whsec_testsecret'),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)

        expect(response.capturedPostHogEvents[0].properties).toMatchObject({
            $hog_function_execution_count: 1,
            account_country: 'US',
            account_name: 'PostHog - modified',
        })
    })

    it('should return 400 if the signature is missing', async () => {
        const response = await tester.invoke(
            {
                signing_secret: 'whsec_testsecret',
            },
            {
                request: {
                    method: 'POST',
                    headers: {},
                    body: {},
                    stringBody: '',
                    query: {},
                },
            }
        )

        expect(response.execResult).toMatchObject({
            httpResponse: {
                status: 400,
                body: 'Missing signature',
            },
        })
    })

    it('should return 400 if the signature is invalid', async () => {
        const response = await tester.invoke(
            {
                signing_secret: 'whsec_testsecret',
            },
            {
                request: createStripeWebhook('whsec_testsecret-not!'),
            }
        )

        expect(response.execResult).toMatchObject({
            httpResponse: {
                status: 400,
                body: 'Bad signature',
            },
        })
    })

    it('should bypass the signature check if bypass_signature_check is true', async () => {
        const response = await tester.invoke(
            {
                signing_secret: '',
                bypass_signature_check: true,
            },
            {
                request: createStripeWebhook('whsec_testsecret'),
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.capturedPostHogEvents).toHaveLength(1)
    })

    it.each([
        ['customer', { customer: 'customer:1234' }],
        ['subscription', { subscription: { customer: 'subscription:1234' } }],
        ['payment_intent', { payment_intent: { customer: 'payment_intent:1234' } }],
        ['id', { id: 'id:1234', object: 'customer' }],
    ])('should capture the event with the correct distinct ID from %s', async (key, body) => {
        const response = await tester.invoke(
            {
                signing_secret: 'whsec_testsecret',
                distinct_id: '',
            },
            {
                request: createStripeWebhook('whsec_testsecret', {
                    ...stripeWebhook,
                    data: {
                        object: body,
                    },
                }),
            }
        )

        expect(response.capturedPostHogEvents).toHaveLength(1)
        expect(response.capturedPostHogEvents[0].distinct_id).toEqual(`${key}:1234`)
    })
})

const createStripeWebhook = (secret: string, body?: Record<string, any>) => {
    const payload = JSON.stringify({
        ...(body ? body : stripeWebhook),
    })

    const timestamp = Math.floor(Date.now() / 1000)
    const signature = crypto.createHmac('sha256', secret).update(`${timestamp}.${payload}`, 'utf8').digest('hex')

    const sigHeader = `t=${timestamp},v1=${signature}`

    return {
        method: 'POST',
        body: parseJSON(payload),
        stringBody: payload,
        headers: {
            'stripe-signature': sigHeader,
        },
        query: {},
    }
}

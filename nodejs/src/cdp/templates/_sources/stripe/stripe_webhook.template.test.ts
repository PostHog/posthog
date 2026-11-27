import crypto from 'crypto'
import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

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

    it.each([
        [
            'diagnostic fields and a second v1 signature',
            (t: number, v1: string) =>
                `t=${t},v1=${v1},v1=${OTHER_SIGNATURE},v0=${OTHER_SIGNATURE},secret=whsec_test,destination=we_test,payload=a1b2c3d4`,
        ],
        ['the matching v1 signature last', (t: number, v1: string) => `t=${t},v1=${OTHER_SIGNATURE},v1=${v1}`],
        ['the signature before the timestamp', (t: number, v1: string) => `v1=${v1},t=${t}`],
    ])('should accept a stripe-signature header with %s', async (_, formatHeader) => {
        const response = await tester.invoke(
            {
                signing_secret: 'whsec_testsecret',
            },
            {
                request: createStripeWebhook('whsec_testsecret', undefined, formatHeader),
            }
        )

        expect(response.execResult).toBeUndefined()
        expect(response.capturedPostHogEvents).toHaveLength(1)
    })

    it.each([null, '', undefined])(
        'should return 400 if signing_secret is %s and bypass_signature_check is false',
        async (signing_secret) => {
            const response = await tester.invoke(
                {
                    signing_secret,
                    bypass_signature_check: false,
                },
                {
                    request: createStripeWebhook('whsec_testsecret'),
                }
            )

            expect(response.execResult).toMatchObject({
                httpResponse: {
                    status: 400,
                    body: 'Signing secret not configured',
                },
            })
        }
    )

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

const OTHER_SIGNATURE = 'f'.repeat(64)

const createStripeWebhook = (
    secret: string,
    body?: Record<string, any>,
    formatHeader = (timestamp: number, signature: string): string => `t=${timestamp},v1=${signature}`
) => {
    const payload = JSON.stringify({
        ...(body ? body : stripeWebhook),
    })

    const timestamp = Math.floor(Date.now() / 1000)
    const signature = crypto.createHmac('sha256', secret).update(`${timestamp}.${payload}`, 'utf8').digest('hex')

    const sigHeader = formatHeader(timestamp, signature)

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

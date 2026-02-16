import crypto from 'crypto'
import { DateTime } from 'luxon'

import { parseJSON } from '~/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
import stripeWebhook from './__tests__/stripe-webhook.json'
import { template } from './stripe.template'

describe('warehouse source stripe template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        const fixedTime = DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate()
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
    })

    it('should return the full request body for a valid signed webhook', async () => {
        const response = await tester.invoke(
            { signing_secret: 'whsec_testsecret', bypass_signature_check: false },
            { request: createStripeWebhook('whsec_testsecret') }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.execResult).toEqual(stripeWebhook)
    })

    it('should return 400 when stripe-signature header is missing', async () => {
        const response = await tester.invoke(
            { signing_secret: 'whsec_testsecret' },
            { request: { method: 'POST', headers: {}, body: {}, stringBody: '', query: {} } }
        )

        expect(response.execResult).toMatchObject({
            httpResponse: { status: 400, body: 'Missing signature' },
        })
    })

    it('should return 400 for an invalid signature', async () => {
        const response = await tester.invoke(
            { signing_secret: 'whsec_testsecret' },
            { request: createStripeWebhook('wrong-secret') }
        )

        expect(response.execResult).toMatchObject({
            httpResponse: { status: 400, body: 'Bad signature' },
        })
    })

    it('should return 405 for non-POST requests', async () => {
        const response = await tester.invoke(
            { signing_secret: 'whsec_testsecret' },
            { request: { method: 'GET', headers: {}, body: {}, stringBody: '', query: {} } }
        )

        expect(response.execResult).toMatchObject({
            httpResponse: { status: 405, body: 'Method not allowed' },
        })
    })

    it('should bypass signature check when configured', async () => {
        const response = await tester.invoke(
            { signing_secret: '', bypass_signature_check: true },
            { request: createStripeWebhook('whsec_testsecret') }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(response.execResult).toEqual(stripeWebhook)
    })

    it('should return 400 when signature header cannot be parsed', async () => {
        const response = await tester.invoke(
            { signing_secret: 'whsec_testsecret' },
            {
                request: {
                    method: 'POST',
                    headers: { 'stripe-signature': 'malformed' },
                    body: stripeWebhook,
                    stringBody: JSON.stringify(stripeWebhook),
                    query: {},
                },
            }
        )

        expect(response.execResult).toMatchObject({
            httpResponse: { status: 400, body: 'Could not parse signature' },
        })
    })
})

const createStripeWebhook = (secret: string, body?: Record<string, any>) => {
    const payload = JSON.stringify(body ?? stripeWebhook)
    const timestamp = Math.floor(Date.now() / 1000)
    const signature = crypto.createHmac('sha256', secret).update(`${timestamp}.${payload}`, 'utf8').digest('hex')

    return {
        method: 'POST',
        body: parseJSON(payload),
        stringBody: payload,
        headers: { 'stripe-signature': `t=${timestamp},v1=${signature}` },
        query: {},
    }
}

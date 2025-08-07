import crypto from 'crypto'
import { DateTime } from 'luxon'

import { parseJSON } from '~/utils/json-parse'

import { TemplateTester } from '../../test/test-helpers'
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
                    headers: {},
                    body: {},
                    stringBody: '',
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
})

const createStripeWebhook = (secret: string, body?: Record<string, any>) => {
    const endpointSecret = secret

    const payload = JSON.stringify({
        id: 'evt_1234',
        object: 'event',
        api_version: '2020-03-02',
        created: 1754571971,
        data: {
            object: {
                id: 'in_1234',
                object: 'invoice',
                account_country: 'US',
                account_name: 'PostHog',
                account_tax_ids: null,
                amount_due: 0,
                amount_overpaid: 0,
                amount_paid: 0,
                amount_remaining: 0,
                amount_shipping: 0,
                application: null,
                application_fee_amount: null,
                attempt_count: 0,
                attempted: true,
                auto_advance: false,
                automatic_tax: {
                    disabled_reason: null,
                    enabled: false,
                    liability: null,
                    provider: null,
                    status: null,
                },
                automatically_finalizes_at: null,
                billing_reason: 'subscription_cycle',
                charge: null,
                collection_method: 'charge_automatically',
                created: 1754568344,
                currency: 'usd',
                custom_fields: null,
                customer: 'cus_1234',
                customer_address: {},
                customer_email: 'test@test.com',
                customer_name: 'Test User',
                customer_phone: null,
                customer_shipping: null,
                customer_tax_exempt: 'none',
                customer_tax_ids: [],
                default_payment_method: null,
                default_source: null,
                default_tax_rates: [],
                description: null,
                discount: null,
                discounts: [],
                due_date: null,
                effective_at: 1754571965,
                ending_balance: 0,
                footer: 'Please note that PostHog does not accept payment by cheque. ',
                from_invoice: null,
                hosted_invoice_url: 'https://invoice.stripe.com/foo',
                invoice_pdf: 'https://pay.stripe.com/invoice/foo/pdf?s=ap',
                issuer: {
                    type: 'self',
                },
                last_finalization_error: null,
                latest_revision: null,
                lines: {
                    object: 'list',
                    data: [],
                    has_more: true,
                    total_count: 11,
                    url: '/v1/invoices/in_1234/lines',
                },
                livemode: true,
                metadata: {},
                next_payment_attempt: null,
                number: '1234',
                on_behalf_of: null,
                paid: true,
                paid_out_of_band: false,
                parent: {
                    quote_details: null,
                    subscription_details: {
                        metadata: {},
                        subscription: 'sub_1234',
                    },
                    type: 'subscription_details',
                },
                payment_intent: null,
                payment_settings: {
                    default_mandate: null,
                    payment_method_options: null,
                    payment_method_types: null,
                },
                period_end: 1754568328,
                period_start: 1751889928,
                post_payment_credit_notes_amount: 0,
                pre_payment_credit_notes_amount: 0,
                quote: null,
                receipt_number: null,
                rendering: {
                    amount_tax_display: null,
                    pdf: null,
                    template: null,
                    template_version: null,
                },
                rendering_options: null,
                shipping_cost: null,
                shipping_details: null,
                starting_balance: 0,
                statement_descriptor: null,
                status: 'paid',
                status_transitions: {
                    finalized_at: 1754571965,
                    marked_uncollectible_at: null,
                    paid_at: 1754571965,
                    voided_at: null,
                },
                subscription: 'sub_1234',
                subscription_details: {
                    metadata: {},
                },
                subtotal: 0,
                subtotal_excluding_tax: 0,
                tax: null,
                tax_percent: null,
                test_clock: null,
                total: 0,
                total_discount_amounts: [],
                total_excluding_tax: 0,
                total_pretax_credit_amounts: [],
                total_tax_amounts: [],
                total_taxes: [],
                transfer_data: null,
                webhooks_delivered_at: 1754568349,
            },
        },
        livemode: true,
        pending_webhooks: 5,
        request: {
            id: null,
            idempotency_key: null,
        },
        type: 'invoice.payment_succeeded',
        ...body,
    })

    const timestamp = Math.floor(Date.now() / 1000)
    const signature = crypto
        .createHmac('sha256', endpointSecret)
        .update(`${timestamp}.${payload}`, 'utf8')
        .digest('hex')

    const sigHeader = `t=${timestamp},v1=${signature}`

    return {
        body: parseJSON(payload),
        stringBody: payload,
        headers: {
            'stripe-signature': sigHeader,
        },
    }
}

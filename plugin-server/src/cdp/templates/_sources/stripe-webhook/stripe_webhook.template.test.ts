import { DateTime } from 'luxon'

import { TemplateTester } from '../../test/test-helpers'
import { template } from './stripe_webhook.template'

// From https://docs.stripe.com/event-destinations#example-snapshot-event-payload
const _createStripeWebhook = () => ({
    id: 'evt_1NG8Du2eZvKYlo2CUI79vXWy',
    object: 'event',
    api_version: '2019-02-19',
    created: 1686089970,
    data: {
        object: {
            id: 'seti_1NG8Du2eZvKYlo2C9XMqbR0x',
            object: 'setup_intent',
            application: null,
            automatic_payment_methods: null,
            cancellation_reason: null,
            client_secret: 'seti_1NG8Du2eZvKYlo2C9XMqbR0x_secret_O2CdhLwGFh2Aej7bCY7qp8jlIuyR8DJ',
            created: 1686089970,
            customer: null,
            description: null,
            flow_directions: null,
            last_setup_error: null,
            latest_attempt: null,
            livemode: false,
            mandate: null,
            metadata: {},
            next_action: null,
            on_behalf_of: null,
            payment_method: 'pm_1NG8Du2eZvKYlo2CYzzldNr7',
            payment_method_options: {
                acss_debit: {
                    currency: 'cad',
                    mandate_options: {
                        interval_description: 'First day of every month',
                        payment_schedule: 'interval',
                        transaction_type: 'personal',
                    },
                    verification_method: 'automatic',
                },
            },
            payment_method_types: ['acss_debit'],
            single_use_mandate: null,
            status: 'requires_confirmation',
            usage: 'off_session',
        },
    },
    livemode: false,
    pending_webhooks: 0,
    request: {
        id: null,
        idempotency_key: null,
    },
    type: 'setup_intent.created',
})

describe('stripe webhook template', () => {
    const tester = new TemplateTester(template)

    beforeEach(async () => {
        await tester.beforeEach()
        jest.useFakeTimers().setSystemTime(DateTime.fromISO('2025-01-01T00:00:00Z').toJSDate())
    })

    it('should invoke the function', async () => {
        const response = await tester.invoke(
            {
                event: '{request.body.eventName}',
                distinct_id: 'hardcoded',
                properties: {
                    root_level: '{request.body.rootLevel}',
                    nested_level: '{request.body.nested.nestedLevel}',
                    missing: '{request.body.missing?.missingvalue}',
                },
            },
            {
                request: {
                    body: _createStripeWebhook(),
                    headers: {},
                    ip: '127.0.0.1',
                },
            }
        )

        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)

        expect(response.capturedPostHogEvents).toMatchInlineSnapshot(`
            [
              {
                "distinct_id": "hardcoded",
                "event": "the event",
                "properties": {
                  "$hog_function_execution_count": 1,
                  "missing": null,
                  "nested_level": "nestedLevelValue",
                  "root_level": "rootLevelValue",
                },
                "team_id": 1,
                "timestamp": "2025-01-01T00:00:00.000Z",
              },
            ]
        `)
    })
})

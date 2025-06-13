import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'source_webhook',
    id: 'template-stripe-webhook',
    name: 'Stripe Webhook',
    description: 'Capture events from Stripe webhooks',
    icon_url: '/static/services/stripe.png',
    category: [],
    hog: `
if(inputs.debug) {
  print('Incoming request:', request.body)
}

// TODO: Validate the headers

postHogCapture({
    'event': inputs.event_name,
    'distinct_id': inputs.distinct_id,
    'properties': request.body.data?.object ?? {}
})
`,
    inputs_schema: [
        {
            key: 'event_name',
            type: 'string',
            label: 'PostHog event name',
            description: 'Determines how the event name should be created',
            default: 'stripe.{request.body.type}',
            secret: false,
            required: true,
        },
        {
            key: 'distinct_id',
            type: 'string',
            label: 'Distinct ID',
            description: 'The distinct ID this event should be associated with',
            default: '{request.body.data?.object?.customer}',
            secret: false,
            required: true,
        },
        {
            key: 'events_to_include',
            type: 'string_list',
            label: 'Events to include',
            description:
                'The Stripe events to be captured. If empty then all events will be captured. See https://docs.stripe.com/api/events/types for the full list of events.',
            secret: false,
            required: true,
        },
    ],
}

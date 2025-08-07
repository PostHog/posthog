import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'source_webhook',
    id: 'template-source-stripe-webhook',
    name: 'Stripe Webhook',
    description: 'Capture an event via a Stripe webhook',
    icon_url: '/static/services/stripe.svg',
    category: ['Revenue', 'Payment'],
    code_language: 'hog',
    code: `let signatureHeader := request.headers['stripe-signature']
  let body := request.stringBody
  
  print('headers', request.headers)
  print('body', body)
  
  
  // Extract t= (timestamp) and v1= (signature) from header
  let headerParts := splitByString(',', signatureHeader)
  let timestamp := null
  let v1Signature := null
  
  for (let _, part in headerParts) {
      let trimmed := trim(part)
      if (trimmed like 't=%') {
          let tParts := splitByString('=', trimmed, 2)
          if (length(tParts) = 2) {
              timestamp := tParts[2]
          }
      }
      if (trimmed like 'v1=%') {
          let v1Parts := splitByString('=', trimmed, 2)
          if (length(v1Parts) = 2) {
              v1Signature := v1Parts[2]
          }
      }
  }
  
  if (empty(timestamp) or empty(v1Signature)) {
      return null
  }
  
  let signedPayload := concat(timestamp, '.', body)
  let computedSignature := sha256HmacChainHex([inputs.signing_secret, signedPayload])
  
  print('sigs', computedSignature, v1Signature)
  
  if (computedSignature != v1Signature) {
      throw Error('Bad signature')
  }

  let properties := inputs.include_all_properties ? request.body.data.object : {}

  for (let key, value in inputs.properties) {
      properties[key] := value
  }

  postHogCapture({
    'event': inputs.event,
    'distinct_id': inputs.distinct_id,
    'properties': properties
  })
  `,

    inputs_schema: [
        {
            type: 'string',
            key: 'signing_secret',
            label: 'Signing secet',
            required: false,
            secret: true,
            hidden: false,
            description: 'Used to validate the webhook came from Stripe',
        },
        {
            type: 'string',
            key: 'event',
            label: 'Event name',
            default: 'stripe.{request.body.type}',
            description: 'The event name to capture.',
        },
        {
            type: 'string',
            key: 'distinct_id',
            label: 'Distinct ID to be used',
            default: '{request.body.data.object.customer}',
            description: 'The distinct ID for the event to be associated with - defaults to the customer ID.',
        },

        {
            key: 'include_all_properties',
            type: 'boolean',
            label: 'Include all properties',
            description:
                'If set, the entire `data.object` will be included as properties. You can override specific webhook attributes below.',
            default: false,
            secret: false,
            required: true,
        },
        {
            key: 'properties',
            type: 'dictionary',
            label: 'Property mapping',
            description:
                'Map of stripe webhook attributes and their values. You can use the filters section to filter out unwanted events.',
            default: {},
            secret: false,
            required: false,
        },

        {
            type: 'boolean',
            key: 'debug',
            label: 'Log payloads',
            required: false,
            default: false,
            secret: false,
            hidden: false,
            description: 'Logs the incoming request for debugging',
        },
    ],
}

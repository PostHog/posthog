import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'source_webhook',
    id: 'template-source-stripe-webhook',
    name: 'Stripe webhook',
    description: 'Capture an event via a Stripe webhook',
    icon_url: '/static/services/stripe.png',
    category: ['Revenue', 'Payment'],
    code_language: 'hog',
    code: `
let body := request.stringBody  

if (not inputs.bypass_signature_check) {
  let signatureHeader := request.headers['stripe-signature']

  if (empty(signatureHeader)) {
    return {
      'httpResponse': {
        'status': 400,
        'body': 'Missing signature',
      }
    }
  }

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
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Could not parse signature',
        }
      }
  }
  
  let signedPayload := concat(timestamp, '.', body)
  let computedSignature := sha256HmacChainHex([inputs.signing_secret, signedPayload])
      
  if (computedSignature != v1Signature) {
      return {
        'httpResponse': {
          'status': 400,
          'body': 'Bad signature',
        }
      }
  }
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
            label: 'Signing secret',
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
            default: true,
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
            key: 'bypass_signature_check',
            label: 'Bypass signature check',
            description: 'If set, the stripe-signature header will not be checked. This is not recommended.',
            default: false,
            required: false,
            secret: false,
        },
    ],
}

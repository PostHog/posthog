import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: false,
    type: 'destination',
    id: 'template-google-pubsub',
    name: 'Google Pub/Sub',
    description: 'Send data to a Google Pub/Sub topic',
    icon_url: '/static/services/google-cloud.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
let headers := () -> {
  'Authorization': f'Bearer {inputs.auth.access_token}',
  'Content-Type': 'application/json'
}
let message := () -> {
  'messageId': event.uuid,
  'data': base64Encode(jsonStringify(inputs.payload)),
  'attributes': inputs.attributes
}
let res := fetch(f'https://pubsub.googleapis.com/v1/{inputs.topicId}:publish', {
  'method': 'POST',
  'headers': headers(),
  'body': jsonStringify({ 'messages': [message()] })
})

if (res.status >= 200 and res.status < 300) {
  print('Event sent successfully!')
} else {
  throw Error(f'Error from pubsub.googleapis.com (status {res.status}): {res.body}')
}
`.trim(),
    inputs_schema: [
        {
            key: 'auth',
            type: 'integration',
            integration: 'google-pubsub',
            label: 'Google Cloud service account',
            secret: false,
            required: true,
        },
        {
            key: 'topicId',
            type: 'string',
            label: 'Topic name',
            secret: false,
            required: true,
        },
        {
            key: 'payload',
            type: 'json',
            label: 'Message Payload',
            default: {
                event: '{event}',
                person: '{person}',
            },
            secret: false,
            required: false,
        },
        {
            key: 'attributes',
            type: 'json',
            label: 'Attributes',
            default: {},
            secret: false,
            required: false,
        },
    ],
}

import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: false,
    type: 'destination',
    id: 'template-google-cloud-storage',
    name: 'Google Cloud Storage',
    description: 'Send data to GCS. This creates a file per event.',
    icon_url: '/static/services/google-cloud-storage.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
let res := fetch(f'https://storage.googleapis.com/upload/storage/v1/b/{encodeURLComponent(inputs.bucketName)}/o?uploadType=media&name={encodeURLComponent(inputs.filename)}', {
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.auth.access_token}',
    'Content-Type': 'application/json'
  },
  'body': inputs.payload
})

if (res.status >= 200 and res.status < 300) {
  print('Event sent successfully!')
} else {
  throw Error('Error sending event', res)
}
`.trim(),
    inputs_schema: [
        {
            key: 'auth',
            type: 'integration',
            integration: 'google-cloud-storage',
            label: 'Google Cloud service account',
            secret: false,
            required: true,
        },
        {
            key: 'bucketName',
            type: 'string',
            label: 'Bucket name',
            secret: false,
            required: true,
        },
        {
            key: 'filename',
            type: 'string',
            label: 'Filename',
            default: '{toDate(event.timestamp)}/{event.timestamp}-{event.uuid}.json',
            secret: false,
            required: true,
        },
        {
            key: 'payload',
            type: 'string',
            label: 'File contents',
            default: "{jsonStringify({ 'event': event, 'person': person })}",
            secret: false,
            required: true,
        },
    ],
}

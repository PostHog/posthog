import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: false,
    type: 'destination',
    id: 'template-airtable',
    name: 'Airtable',
    description: 'Creates Airtable records',
    icon_url: '/static/services/airtable.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
let url := f'https://api.airtable.com/v0/{inputs.base_id}/{inputs.table_name}'

let payload := {
  'headers': {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {inputs.access_token}'
  },
  'body': {
    'fields': inputs.fields,
    'typecast': true
  },
  'method': 'POST'
}

if (inputs.debug) {
  print('Request', url, payload)
}

let res := fetch(url, payload);

if (inputs.debug) {
  print('Response', res.status, res.body);
}
if (res.status >= 400) {
    throw Error(f'Error from api.airtable.com (status {res.status}): {res.body}')
}
`.trim(),
    inputs_schema: [
        {
            key: 'access_token',
            type: 'string',
            label: 'Airtable access token',
            secret: true,
            required: true,
            description: 'Create this at https://airtable.com/create/tokens',
        },
        {
            key: 'base_id',
            type: 'string',
            label: 'Airtable base ID',
            secret: false,
            required: true,
            description: 'Find this at https://airtable.com/developers/web/api/introduction',
        },
        {
            key: 'table_name',
            type: 'string',
            label: 'Table name',
            secret: false,
            required: true,
        },
        {
            key: 'fields',
            type: 'json',
            label: 'Fields',
            default: {
                Timestamp: '{event.timestamp}',
                'Person Name': '{person.name}',
            },
            secret: false,
            required: true,
            description: 'Map field names from Airtable to properties from events and person records.',
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the response of http calls for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
}

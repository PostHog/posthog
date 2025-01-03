import { HogFunctionTemplate } from '../../helpers'

export const template: HogFunctionTemplate = {
    status: 'beta',
    type: 'destination',
    id: 'template-Intercom',
    name: 'Intercom',
    description: 'Send events and contact information to Intercom',
    icon_url: '/static/services/intercom.png',
    category: ['Customer Success'],
    hog: `
if (empty(inputs.email)) {
    print('\`email\` input is empty. Skipping.')
    return
}

let res := fetch(f'https://{inputs.host}/events', {
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.access_token}',
    'Content-Type': 'application/json',
    'Accept': 'application/json'
  },
  'body': {
    'event_name': event.event,
    'created_at': toInt(toUnixTimestamp(toDateTime(event.timestamp))),
    'email': inputs.email,
    'id': event.distinct_id,
  }
})

if (res.status >= 200 and res.status < 300) {
    print('Event sent successfully!')
    return
}

if (res.status == 404) {
    throw Error('No existing contact found for email')
    return
}

throw Error(f'Error from intercom api (status {res.status}): {res.body}')
`,
    inputs_schema: [
        {
            key: 'access_token',
            type: 'string',
            label: 'Intercom access token',
            description:
                'Create an Intercom app (https://developers.intercom.com/docs/build-an-integration/learn-more/authentication), then go to Configure > Authentication to find your token.',
            secret: true,
            required: true,
        },
        {
            key: 'host',
            type: 'choice',
            choices: [
                {
                    label: 'US (api.intercom.io)',
                    value: 'api.intercom.io',
                },
                {
                    label: 'EU (api.eu.intercom.com)',
                    value: 'api.eu.intercom.com',
                },
            ],
            label: 'Data region',
            description: 'Use the EU variant if your Intercom account is based in the EU region',
            default: 'api.intercom.io',
            secret: false,
            required: true,
        },
        {
            key: 'email',
            type: 'string',
            label: 'Email of the user',
            description:
                'Where to find the email for the contact to be created. You can use the filters section to filter out unwanted emails or internal users.',
            default: '{person.properties.email}',
            secret: false,
            required: true,
        },
    ],
    filters: {
        events: [{ id: '$identify', name: '$identify', type: 'events', order: 0 }],
        actions: [],
        filter_test_accounts: true,
    },
}

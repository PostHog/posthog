import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: false,
    type: 'destination',
    id: 'template-flywheel',
    name: 'Flywheel',
    description: 'Send events and user data to Flywheel for customer communication workflows',
    icon_url: '/static/services/flywheel.png',
    category: ['Customer Success'],
    code_language: 'hog',
    code: `
let res := fetch('https://api.flywheel.cx/posthog/event-receiver', {
  'body': {
    'event': event,
    'person': person
  },
  'method': 'POST',
  'headers': {
    'Authorization': inputs.apiKey,
    'Auth-Type': 'api',
    'Content-Type': 'application/json'
  }
});

if (res.status >= 400) {
  throw Error(f'Failed to send event to Flywheel: {res.status}: {res.body}');
}
`.trim(),
    inputs_schema: [
        {
            key: 'apiKey',
            type: 'string',
            label: 'Flywheel Write API Key',
            description: 'Your Flywheel write API key. Find this in your Flywheel dashboard.',
            secret: true,
            required: true,
        },
    ],
}

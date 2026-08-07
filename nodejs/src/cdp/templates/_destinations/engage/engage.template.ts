import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: false,
    type: 'destination',
    id: 'template-engage-so',
    name: 'Engage.so',
    description: 'Send events to Engage.so',
    icon_url: '/static/services/engage.png',
    category: ['Email Marketing'],
    code_language: 'hog',
    code: `
fetch('https://api.engage.so/posthog', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {base64Encode(f'{inputs.public_key}:{inputs.private_key}')}',
        'Content-Type': 'application/json'
    },
    'body': event
})
`.trim(),
    inputs_schema: [
        {
            key: 'public_key',
            type: 'string',
            label: 'Public key',
            description: 'Get your public key from your Engage dashboard (Settings -> Account)',
            secret: true,
            required: true,
        },
        {
            key: 'private_key',
            type: 'string',
            label: 'Private key',
            description: 'Get your private key from your Engage dashboard (Settings -> Account)',
            secret: true,
            required: true,
        },
    ],
    filters: {
        events: [
            {
                id: '$identify',
                name: '$identify',
                type: 'events',
                order: 0,
            },
            {
                id: '$set',
                name: '$set',
                type: 'events',
                order: 1,
            },
            {
                id: '$groupidentify',
                name: '$groupidentify',
                type: 'events',
                order: 2,
            },
            {
                id: '$unset',
                name: '$unset',
                type: 'events',
                order: 3,
            },
            {
                id: '$create_alias',
                name: '$create_alias',
                type: 'events',
                order: 4,
            },
        ],
        actions: [],
        filter_test_accounts: true,
    },
}

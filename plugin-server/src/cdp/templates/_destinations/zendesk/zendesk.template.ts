import { HogFunctionTemplate } from '../../helpers'

export const template: HogFunctionTemplate = {
    status: 'beta',
    type: 'destination',
    id: 'template-zendesk',
    name: 'Zendesk',
    description: 'Update contacts in Zendesk',
    category: ['Customer Success'],
    icon_url: '/static/services/zendesk.png',
    hog: `
if (empty(inputs.email) or empty(inputs.name)) {
    print('\`email\` or \`name\` input is empty. Not creating a contact.')
    return
}

let body := {
    'user': {
        'email': inputs.email,
        'name': inputs.name,
        'skip_verify_email': true,
        'user_fields': {}
    }
}

for (let key, value in inputs.attributes) {
    if (not empty(value) and key != 'email' and key != 'name') {
        body.user.user_fields[key] := value
    }
}

fetch(f'https://{inputs.subdomain}.zendesk.com/api/v2/users/create_or_update', {
  'headers': {
    'Authorization': f'Basic {base64Encode(f'{inputs.admin_email}/token:{inputs.token}')}',
    'Content-Type': 'application/json'
  },
  'body': body,
  'method': 'POST'
});
`,
    inputs_schema: [
        {
            key: 'subdomain',
            type: 'string',
            label: 'Zendesk subdomain',
            description:
                'Generally, Your Zendesk URL has two parts: a subdomain name you chose when you set up your account, followed by zendesk.com (for example: mycompany.zendesk.com). Please share the subdomain name with us so we can set up your account.',
            secret: false,
            required: true,
        },
        {
            key: 'admin_email',
            type: 'string',
            label: 'API user email',
            secret: true,
            required: true,
            description:
                'Enter the email of an admin in Zendesk. Activity using the API key will be attributed to this user.',
        },
        {
            key: 'token',
            type: 'string',
            label: 'API token',
            secret: true,
            required: true,
            description: 'Enter your Zendesk API Token',
        },
        {
            key: 'email',
            type: 'string',
            label: 'User email',
            default: '{person.properties.email}',
            secret: false,
            required: true,
            description: 'The email of the user you want to create or update.',
        },
        {
            key: 'name',
            type: 'string',
            label: 'User name',
            default: '{person.properties.name}',
            secret: false,
            required: true,
            description: 'The name of the user you want to create or update.',
        },
        {
            key: 'attributes',
            type: 'dictionary',
            label: 'Attribute mapping',
            description:
                "Map of Zendesk user fields and their values. You'll need to create User fields in Zendesk for these to work.",
            default: {
                phone: '{person.properties.phone}',
                plan: '{person.properties.plan}',
            },
            secret: false,
            required: false,
        },
    ],
    filters: {
        events: [
            { id: '$identify', name: '$identify', type: 'events', order: 0 },
            { id: '$set', name: '$set', type: 'events', order: 1 },
        ],
        actions: [],
        filter_test_accounts: true,
    },
}

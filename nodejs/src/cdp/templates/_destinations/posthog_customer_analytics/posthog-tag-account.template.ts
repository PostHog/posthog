import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-tag-account',
    name: 'Tag account',
    description: 'Add, replace, or remove tags on a Customer analytics account.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.external_id)) {
  throw Error('Account external ID is required')
}

if (empty(inputs.tags)) {
  throw Error('At least one tag is required')
}

let response := postHogUpdateAccount({
  'external_id': inputs.external_id,
  'updates': {
    'tags': inputs.tags,
    'tags_mode': (not empty(inputs.tags_mode)) ? inputs.tags_mode : 'add'
  }
})

if (response.status == 404) {
  throw Error(f'Account not found: {inputs.external_id}')
}

if (response.status >= 400) {
  throw Error(f'Failed to tag account ({response.status}): {response.body.error ?? response.body}')
}

print(f'Tagged account {inputs.external_id}')
return response.body
`,
    inputs_schema: [
        {
            key: 'external_id',
            type: 'string',
            label: 'Account external ID',
            secret: false,
            required: true,
            description:
                'The external ID of the account to tag — the group key the account is linked to. Available from trigger event or group properties.',
        },
        {
            key: 'tags',
            type: 'posthog_ticket_tags',
            label: 'Tags',
            secret: false,
            required: true,
            description: 'Tags to apply to the account.',
        },
        {
            key: 'tags_mode',
            type: 'choice',
            label: 'Tag mode',
            secret: false,
            required: false,
            default: 'add',
            choices: [
                { label: 'Add to existing tags', value: 'add' },
                { label: 'Replace all tags', value: 'set' },
                { label: 'Remove these tags', value: 'remove' },
            ],
            description:
                'How the tags above are applied. Add (default) is safe when multiple workflows tag the same account.',
        },
    ],
}

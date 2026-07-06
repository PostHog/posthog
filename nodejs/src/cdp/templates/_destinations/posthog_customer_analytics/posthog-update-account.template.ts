import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-update-account',
    name: 'Update account',
    description: 'Assign role contacts (CSM, account executive, account owner) or tag a Customer analytics account.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.external_id)) {
  throw Error('Account external ID is required')
}

let updates := {}

if (not empty(inputs.csm)) {
  updates.csm := inputs.csm
}

if (not empty(inputs.account_executive)) {
  updates.account_executive := inputs.account_executive
}

if (not empty(inputs.account_owner)) {
  updates.account_owner := inputs.account_owner
}

if (not empty(inputs.tags)) {
  updates.tags := inputs.tags
  updates.tags_mode := (not empty(inputs.tags_mode)) ? inputs.tags_mode : 'add'
}

let response := postHogUpdateAccount({
  'external_id': inputs.external_id,
  'updates': updates
})

if (response.status == 404) {
  throw Error(f'Account not found: {inputs.external_id}')
}

if (response.status >= 400) {
  throw Error(f'Failed to update account: {response.status}')
}

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
                'The external ID of the account to update — the group key the account is linked to. Available from trigger event or group properties.',
        },
        {
            key: 'csm',
            type: 'posthog_assignee',
            label: 'Customer success manager',
            secret: false,
            required: false,
            description:
                'Assign a CSM to the account. Only users can be assigned, not roles. Leave empty to keep current.',
        },
        {
            key: 'account_executive',
            type: 'posthog_assignee',
            label: 'Account executive',
            secret: false,
            required: false,
            description:
                'Assign an account executive to the account. Only users can be assigned, not roles. Leave empty to keep current.',
        },
        {
            key: 'account_owner',
            type: 'posthog_assignee',
            label: 'Account owner',
            secret: false,
            required: false,
            description:
                'Assign an account owner to the account. Only users can be assigned, not roles. Leave empty to keep current.',
        },
        {
            key: 'tags',
            type: 'posthog_ticket_tags',
            label: 'Tags',
            secret: false,
            required: false,
            description: 'Tags to apply to the account. Leave empty to keep current tags.',
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

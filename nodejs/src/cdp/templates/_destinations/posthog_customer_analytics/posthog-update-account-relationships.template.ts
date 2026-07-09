import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-update-account-relationships',
    name: 'Update account relationships',
    description: 'Assign users to relationship roles on a Customer analytics account.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.external_id)) {
  throw Error('Account external ID is required')
}

if (empty(inputs.relationships)) {
  throw Error('At least one relationship assignment is required')
}

let response := postHogUpdateAccount({
  'external_id': inputs.external_id,
  'updates': {
    'relationships': inputs.relationships
  }
})

if (response.status == 404) {
  throw Error(f'Account not found: {inputs.external_id}')
}

if (response.status >= 400) {
  throw Error(f'Failed to update account relationships ({response.status}): {response.body.error ?? response.body}')
}

print(f'Updated relationships on account {inputs.external_id}')
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
            key: 'relationships',
            type: 'customer_analytics_account_relationships',
            label: 'Relationship assignments',
            secret: false,
            required: true,
            description:
                'Map each relationship definition to a user assignment. Set a user to assign them; set to "Clear assignment" to end the current assignment.',
        },
    ],
}

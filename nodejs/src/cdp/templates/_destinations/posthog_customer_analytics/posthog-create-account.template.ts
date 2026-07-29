import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from './api-error'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-create-account',
    name: 'Create account',
    description: 'Create a Customer analytics account, or continue if it already exists.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.external_id)) {
  throw Error('Account external ID is required. Check that the trigger event has a group for the account group type.')
}

let response := postHogCreateAccount({
  'external_id': inputs.external_id,
  'name': inputs.name,
  'tags': inputs.tags
})

if (response.status >= 400) {
  throw Error(f'Failed to create account ({response.status}): {apiErrorMessage(response)}')
}

if (response.body.created) {
  print(f'Created account {inputs.external_id}')
} else {
  print(f'Account {inputs.external_id} already exists')
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
                'The external ID to create the account under. This is the group key the account gets linked to, available from the trigger event or group properties.',
        },
        {
            key: 'name',
            type: 'string',
            label: 'Account name',
            secret: false,
            required: false,
            description: 'Name to show in the account list. Defaults to the external ID when left empty.',
        },
        {
            key: 'tags',
            type: 'posthog_ticket_tags',
            label: 'Tags',
            secret: false,
            required: false,
            description: 'Tags to add to the new account. Ignored when the account already exists.',
        },
    ],
}

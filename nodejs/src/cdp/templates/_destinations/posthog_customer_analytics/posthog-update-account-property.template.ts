import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from './api-error'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-update-account-property',
    name: 'Update account property',
    description: 'Set custom property values on a Customer analytics account.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.external_id)) {
  throw Error('Account external ID is required')
}

let response := postHogSetAccountProperties({
  'external_id': inputs.external_id,
  'properties': inputs.properties
})

if (response.status == 404) {
  throw Error(f'Account not found: {inputs.external_id}')
}

if (response.status >= 400) {
  throw Error(f'Failed to update account properties ({response.status}): {apiErrorMessage(response)}')
}

print(f'Updated custom properties on account {inputs.external_id}')
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
            key: 'properties',
            type: 'customer_analytics_account_properties',
            label: 'Properties to set',
            secret: false,
            required: true,
            description: 'Custom property values to set on the account.',
        },
    ],
}

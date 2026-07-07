import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-get-account',
    name: 'Get account',
    description: 'Fetch a Customer analytics account into a workflow variable.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.external_id)) {
  throw Error('Account external ID is required')
}

let response := postHogGetAccount({'external_id': inputs.external_id})

if (response.status == 404) {
  throw Error(f'Account not found: {inputs.external_id}')
}

if (response.status != 200) {
  throw Error(f'Failed to fetch account: {response.status}')
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
                'The external ID of the account to fetch — the group key the account is linked to. Available from trigger event or group properties.',
        },
    ],
}

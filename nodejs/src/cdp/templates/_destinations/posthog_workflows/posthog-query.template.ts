import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-query',
    name: 'PostHog query',
    description: 'Run a HogQL query against PostHog data and store the result',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom', 'Analytics'],
    code_language: 'hog',
    code: `
if (empty(inputs.endpoint_name)) {
  throw Error('Endpoint is required')
}

let response := postHogQuery({'endpoint_name': inputs.endpoint_name})

if (response.status != 200) {
  throw Error(f'Query failed with status: {response.status}')
}

return response.body
`,
    inputs_schema: [
        {
            key: 'endpoint_name',
            type: 'endpoint',
            label: 'Endpoint',
            secret: false,
            required: true,
            templating: false,
            default: '',
            description: 'The name of the endpoint to query.',
        },
    ],
}

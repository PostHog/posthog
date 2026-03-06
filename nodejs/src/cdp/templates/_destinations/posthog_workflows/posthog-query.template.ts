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
if (empty(inputs.query)) {
  throw Error('Query is required')
}

let response := postHogQuery({'query': inputs.query})

if (response.status != 200) {
  throw Error(f'Query failed with status: {response.status}')
}

return response.body
`,
    inputs_schema: [
        {
            key: 'query',
            type: 'hogql',
            label: 'HogQL query',
            secret: false,
            required: true,
            templating: false,
            default: 'SELECT event, count() AS count FROM events GROUP BY event ORDER BY count DESC LIMIT 10',
            description: 'The HogQL query to run against PostHog data.',
        },
    ],
}

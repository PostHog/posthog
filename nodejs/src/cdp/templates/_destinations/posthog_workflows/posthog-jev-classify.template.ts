import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-jev-classify',
    name: 'Classify with Jev',
    description: 'Ask Jev to pick one category for the context. Returns the category and its confidence.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

let response := postHogClassify({
  'question': inputs.question,
  'context': inputs.context,
  'categories': inputs.categories
})

if (response.status >= 400) {
  throw Error(f'Could not classify ({response.status}): {apiErrorMessage(response)}')
}

return response.body
`,
    inputs_schema: [
        {
            key: 'question',
            type: 'string',
            label: 'Question',
            required: true,
            // Event data goes in the context, so it can never become part of the instructions.
            templating: false,
            description: 'What Jev should decide, for example "Which team should handle this ticket?"',
        },
        {
            key: 'context',
            type: 'json',
            label: 'Context',
            required: true,
            default: { subject: '{event.properties.subject}', message: '{event.properties.message}' },
            description: 'The data Jev reads to decide. Use event properties or variables from earlier steps.',
        },
        {
            key: 'categories',
            type: 'dictionary',
            label: 'Categories',
            required: true,
            templating: false,
            default: { spam: 'Cold outreach, marketing or automated mail', support: 'A customer asking for help' },
            description: 'Each category and when it applies. Enter 2 to 16 categories.',
        },
    ],
}

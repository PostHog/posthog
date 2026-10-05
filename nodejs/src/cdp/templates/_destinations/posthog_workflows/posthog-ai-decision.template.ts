import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-ai-decision',
    name: 'AI decision (Jeeeeeeeeev)',
    description: 'Ask Jev to pick one of your options for the context. Returns the decision and its confidence.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

let response := postHogAiDecision({
  'question': inputs.question,
  'context': inputs.context,
  'options': inputs.options
})

if (response.status >= 400) {
  throw Error(f'Could not decide ({response.status}): {apiErrorMessage(response)}')
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
            key: 'options',
            type: 'dictionary',
            label: 'Options',
            required: true,
            templating: false,
            default: { spam: 'Cold outreach, marketing or automated mail', support: 'A customer asking for help' },
            description:
                'Each option and when it applies. Enter 2 to 16 options. For a yes or no question, enter yes and no.',
        },
    ],
}

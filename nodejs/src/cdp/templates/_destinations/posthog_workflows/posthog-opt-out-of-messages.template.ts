import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-opt-out-of-messages',
    name: 'Opt out of messages',
    description: 'Opt the recipient out of a message category, or of all marketing messages.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

let response := postHogOptOutOfMessages({
  'category_id': inputs.category_id,
  'identifier': inputs.identifier
})

if (response.status >= 400) {
  throw Error(f'Could not opt the recipient out ({response.status}): {apiErrorMessage(response)}')
}

print(response.body.detail)
`,
    inputs_schema: [
        {
            key: 'category_id',
            type: 'string',
            label: 'Message category',
            required: true,
            // The builder renders a category picker for this input. The callback compares the value with the
            // categories the saved workflow names, so it can't be a template.
            hidden: true,
            templating: false,
            description: 'The message category to opt the recipient out of, or $all for all marketing messages.',
        },
        {
            key: 'identifier',
            type: 'string',
            label: 'Recipient',
            required: true,
            default: '{person.properties.email}',
            description:
                "Who to opt out. Use the same value as the email step's recipient, usually the person's email.",
        },
    ],
}

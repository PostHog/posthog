import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-set-variable',
    name: 'Set workflow variable',
    description: 'Set a variable value in the workflow',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom', 'Analytics'],
    code_language: 'hog',
    code: `
return inputs.value
`,
    inputs_schema: [
        {
            key: 'value',
            type: 'string',
            label: 'Value',
            secret: false,
            required: true,
            description: 'The value to set for the variable.',
        },
    ],
}

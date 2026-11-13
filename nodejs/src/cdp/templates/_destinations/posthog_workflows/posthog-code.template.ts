import { HogFunctionTemplate } from '~/cdp/types'

// A code step runs the bytecode compiled from its own action config, never this template's code.
export const template: HogFunctionTemplate = {
    free: false,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-code',
    name: 'Code',
    description: 'Run your own Hog code in a workflow step',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
return null
`,
    inputs_schema: [
        {
            key: 'params',
            type: 'dictionary',
            label: 'Parameters',
            secret: false,
            required: false,
            description: 'Values the code reads as inputs.params.<key>. Values can use templating.',
        },
        {
            key: 'secrets',
            type: 'dictionary',
            label: 'Secrets',
            secret: true,
            required: false,
            templating: false,
            description:
                'Values the code reads as inputs.secrets.<key>, such as API tokens. These are encrypted, hidden after saving, and kept out of the logs. Values are used exactly as entered, without templating.',
        },
    ],
}

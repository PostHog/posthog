import { HogFunctionInputSchemaType } from '~/cdp/types'

export const webhookHeaderInputs: HogFunctionInputSchemaType[] = [
    {
        key: 'headers',
        type: 'dictionary',
        label: 'Headers',
        secret: false,
        required: false,
        default: { 'Content-Type': 'application/json' },
        description:
            'HTTP headers to send in the request. Put API tokens and other credentials in Secret headers instead.',
    },
    {
        key: 'secret_headers',
        type: 'dictionary',
        label: 'Secret headers',
        secret: true,
        required: false,
        templating: false,
        description:
            'HTTP headers that hold a credential, such as an API token. These are encrypted, hidden after saving, and kept out of the logs. Values are sent exactly as entered, without templating, and replace a plaintext header of the same name.',
    },
]

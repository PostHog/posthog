import { HogFunctionTemplateType } from '~/types'

export const HOG_FUNCTION_TEMPLATES: HogFunctionTemplateType[] = [
    {
        id: 'template-webhook',
        name: 'HogHook',
        description: 'Sends a webhook templated by the incoming event data',
        hog: "fetch(inputs.url, {\n  'headers': inputs.headers,\n  'body': inputs.payload,\n  'method': inputs.method\n});",
        inputs_schema: [
            {
                key: 'url',
                type: 'string',
                label: 'Webhook URL',
                secret: false,
                required: true,
            },
            {
                key: 'method',
                type: 'choice',
                label: 'Method',
                secret: false,
                choices: [
                    {
                        label: 'POST',
                        value: 'POST',
                    },
                    {
                        label: 'PUT',
                        value: 'PUT',
                    },
                    {
                        label: 'GET',
                        value: 'GET',
                    },
                    {
                        label: 'DELETE',
                        value: 'DELETE',
                    },
                ],
                required: false,
            },
            {
                key: 'payload',
                type: 'json',
                label: 'JSON Payload',
                secret: false,
                required: false,
            },
            {
                key: 'headers',
                type: 'dictionary',
                label: 'Headers',
                secret: false,
                required: false,
            },
        ],
    },
]

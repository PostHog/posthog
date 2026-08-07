import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'stable',
    free: false,
    type: 'destination',
    id: 'template-make',
    name: 'Make',
    description: 'Triggers a webhook based scenario',
    icon_url: '/static/services/make.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (not match(inputs.webhookUrl, '^https://hook.[^/]+.make.com/?.*')) {
    throw Error('Invalid URL. The URL should match the format: https://hook.<region>.make.com/<hookUrl>')
}

let res := fetch(inputs.webhookUrl, {
    'body': inputs.body,
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    }
});

if (res.status >= 400) {
    throw Error(f'Error from make.com (status {res.status}): {res.body}')
}
`.trim(),
    inputs_schema: [
        {
            key: 'webhookUrl',
            type: 'string',
            label: 'Webhook URL',
            description: 'See this page on how to generate a Webhook URL: https://www.make.com/en/help/tools/webhooks',
            secret: false,
            required: true,
        },
        {
            key: 'body',
            type: 'json',
            label: 'JSON Body',
            default: {
                data: {
                    eventUuid: '{event.uuid}',
                    event: '{event.event}',
                    teamId: '{project.id}',
                    distinctId: '{event.distinct_id}',
                    properties: '{event.properties}',
                    elementsChain: '{event.elementsChain}',
                    timestamp: '{event.timestamp}',
                    person: {
                        uuid: '{person.id}',
                        properties: '{person.properties}',
                    },
                },
            },
            secret: false,
            required: true,
        },
    ],
}

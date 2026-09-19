import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'alpha',
    type: 'destination',
    id: 'template-typesafe-classify',
    name: 'Classify with TypeSafe',
    description: 'Ask a classification question about selected context. Return the category and confidence.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.question) or empty(inputs.context)) {
    throw Error('TypeSafe needs a question and context. Complete both inputs.')
}
if (typeof(inputs.categories) != 'object' or empty(inputs.categories)) {
    throw Error('TypeSafe needs categories. Enter a JSON object with category names and descriptions.')
}
for (let name, description in inputs.categories) {
    if (empty(name) or typeof(description) != 'string' or empty(description)) {
        throw Error('Each TypeSafe category needs a name and description.')
    }
}

let response := fetch('https://api.typesafe.ai/v1/systemone', {
    'method': 'POST',
    'headers': {'Content-Type': 'application/json'},
    'bearer_token_input': 'api_key',
    'body': {
        'model': 'jev-1.13.0',
        'state': inputs.context,
        'questions': {
            'category': {
                'type': 'choice',
                'instructions': inputs.question,
                'criteria': inputs.categories
            }
        }
    }
})

if (response.status < 200 or response.status >= 300) {
    throw Error(f'TypeSafe request failed with status {response.status}. Check the API key and inputs, then retry.')
}

let answer := response.body?.answers?.category
if (answer?.type != 'choice' or typeof(answer?.choice) != 'string' or not has(keys(inputs.categories), answer.choice)
    or typeof(answer?.confidence) not in ('integer', 'float') or not (answer.confidence >= 0 and answer.confidence <= 1)) {
    throw Error('TypeSafe returned an invalid answer. Retry the step.')
}

return {'category': answer.choice, 'confidence': answer.confidence}
`,
    inputs_schema: [
        {
            key: 'api_key',
            type: 'string',
            label: 'TypeSafe API key',
            secret: true,
            templating: false,
            required: true,
            description: 'Your TypeSafe API key. Stored as an encrypted secret.',
        },
        {
            key: 'question',
            type: 'string',
            label: 'Question',
            required: true,
            templating: false,
            description: 'Ask which category fits the context. Include any rules for the decision.',
        },
        {
            key: 'context',
            type: 'json',
            label: 'Context',
            required: true,
            description: 'Select the data to send to TypeSafe. Use event properties or variables from earlier steps.',
        },
        {
            key: 'categories',
            type: 'json',
            label: 'Categories',
            required: true,
            templating: false,
            description:
                'A JSON object with category names as keys and descriptions as values. Include a fallback category.',
        },
    ],
}

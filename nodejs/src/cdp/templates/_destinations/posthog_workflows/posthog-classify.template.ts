import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-classify',
    name: 'JEV classification',
    description: 'Classify text into one of your labels and save the result in a workflow variable.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}
let response := postHogClassify({
    'text': inputs.text,
    'instructions': inputs.instructions,
    'labels': inputs.labels
})
if (response.status >= 400) {
    throw Error(f'Classification failed ({response.status}): {apiErrorMessage(response)}')
}
return response.body
`,
    inputs_schema: [
        {
            key: 'text',
            type: 'string',
            label: 'Text to classify',
            secret: false,
            required: true,
            description: 'Text from an event property or workflow variable. Maximum 8 KiB.',
        },
        {
            key: 'instructions',
            type: 'string',
            label: 'Classification instructions',
            secret: false,
            required: true,
            templating: false,
            default: 'Choose the label that best describes the text.',
            description: 'Describe how JEV should choose a label. The text is sent separately from these instructions.',
        },
        {
            key: 'labels',
            type: 'dictionary',
            label: 'Labels',
            secret: false,
            required: true,
            templating: false,
            default: { positive: 'Positive sentiment', negative: 'Negative sentiment', neutral: 'Neutral sentiment' },
            description: 'Add 2 to 16 labels. Each key is a label and each value describes when to use it.',
        },
    ],
}

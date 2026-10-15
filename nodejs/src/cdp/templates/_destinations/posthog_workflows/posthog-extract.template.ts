import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-extract',
    name: 'Extract with AI',
    description:
        'Ask an AI model to read the output of an earlier step and fill named fields from it, each with its own instruction.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

let response := postHogExtract({
  'context': inputs.context,
  'task_run_id': inputs.task_run_id,
  'fields': inputs.fields
})

if (response.status >= 400) {
  throw Error(f'Could not extract ({response.status}): {apiErrorMessage(response)}')
}

return response.body.values
`,
    inputs_schema: [
        {
            key: 'task_run_id',
            type: 'string',
            label: 'AI task run',
            required: false,
            default: '{variables.task.run_id}',
            description:
                'The run of an AI task step earlier in this workflow. The model reads its full final message, which the task variable cuts short. Leave it empty to read the text below.',
        },
        {
            key: 'context',
            type: 'json',
            label: 'Text to read',
            required: false,
            default: { message: '{variables.task.final_message}' },
            description:
                'The output the model reads when no AI task run is set, such as a webhook response. Use variables from earlier steps.',
        },
        {
            key: 'fields',
            type: 'dictionary',
            label: 'Fields',
            required: true,
            // Event data goes in the text to read, so it can never become part of the instructions.
            templating: false,
            default: {
                pr_url: 'The URL of the pull request the agent opened',
                summary: 'One sentence on what the agent did',
            },
            description:
                'Each field name and what to put in it. Map a field to a variable under Output variables with the field name as the result path. The variable type sets the field type.',
        },
    ],
}

import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-report-customer-task',
    name: 'Report to customer task',
    description:
        "Write an AI agent's result back to a Customer analytics customer task, then close it or hand it back to a person.",
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.customer_task_id)) {
  throw Error('Enter a customer task ID')
}
if (empty(inputs.report)) {
  throw Error('Enter a report')
}
if (empty(inputs.outcome)) {
  throw Error('Choose an outcome')
}
let payload := {
  'customer_task_id': inputs.customer_task_id,
  'report': inputs.report,
  'outcome': inputs.outcome
}
if (not empty(inputs.task_id)) {
  payload.task_id := inputs.task_id
}
if (not empty(inputs.task_run_id)) {
  payload.task_run_id := inputs.task_run_id
}
let response := postHogReportCustomerTask(payload)
if (response.status < 200 or response.status >= 300) {
  throw Error(f'Failed to report to customer task ({response.status}): {apiErrorMessage(response)}')
}
return response.body
`,
    inputs_schema: [
        {
            key: 'customer_task_id',
            type: 'string',
            label: 'Customer task',
            secret: false,
            required: true,
            description: 'The id of the customer task the agent worked on.',
        },
        {
            key: 'report',
            type: 'string',
            label: 'Report',
            secret: false,
            required: true,
            description: 'What the agent did and what is left. Supports variable templating.',
        },
        {
            key: 'outcome',
            type: 'choice',
            label: 'Outcome',
            secret: false,
            required: true,
            default: 'completed',
            choices: [
                { label: 'Completed', value: 'completed' },
                { label: 'Needs a person', value: 'needs_human' },
            ],
            description: 'Completed closes the task. Needs a person hands it back open to the person who assigned it.',
        },
        {
            key: 'task_id',
            type: 'string',
            label: 'AI task id',
            secret: false,
            required: false,
            description: 'The AI task that did the work, for the activity log.',
        },
        {
            key: 'task_run_id',
            type: 'string',
            label: 'AI task run id',
            secret: false,
            required: false,
            description: 'The run that did the work. Repeated reports for the same run are ignored.',
        },
    ],
}

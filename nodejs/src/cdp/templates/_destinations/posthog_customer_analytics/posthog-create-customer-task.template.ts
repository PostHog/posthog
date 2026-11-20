import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-create-customer-task',
    name: 'Create customer task',
    description:
        'Create a Customer analytics task with an optional account, assignee, and due date. All fields support workflow variables.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.name)) {
  throw Error('Enter a task name')
}
let payload := { 'name': inputs.name }
if (not empty(inputs.description)) {
  payload.description := inputs.description
}
if (not empty(inputs.account_id)) {
  payload.account_id := inputs.account_id
}
if (not empty(inputs.assigned_to_id)) {
  payload.assigned_to_id := inputs.assigned_to_id
}
if (not empty(inputs.due_at)) {
  payload.due_at := inputs.due_at
}
let response := postHogCreateCustomerTask(payload)
if (response.status < 200 or response.status >= 300) {
  throw Error(f'Failed to create customer task ({response.status}): {apiErrorMessage(response)}')
}
if (typeof(response.body) != 'object' or typeof(response.body.id) != 'string' or not match(response.body.id, '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')) {
  throw Error('Failed to create customer task: the server did not return a task ID')
}
return response.body
`,
    inputs_schema: [
        {
            key: 'name',
            type: 'string',
            label: 'Task name',
            secret: false,
            required: true,
            description: 'What needs to be done.',
        },
        {
            key: 'description',
            type: 'string',
            label: 'Description',
            secret: false,
            required: false,
            description: 'Additional details for the person completing the task.',
        },
        {
            key: 'account_id',
            type: 'string',
            label: 'Account',
            secret: false,
            required: false,
            description:
                'The account UUID from a Get account or Create account step. Leave empty for no linked account.',
        },
        {
            key: 'assigned_to_id',
            type: 'string',
            label: 'Assignee',
            secret: false,
            required: false,
            description: 'The numeric ID of a project member. Leave empty to create an unassigned task.',
        },
        {
            key: 'due_at',
            type: 'string',
            label: 'Due date',
            secret: false,
            required: false,
            description: 'A date and time with a timezone, such as 2030-01-15T17:00:00Z.',
        },
    ],
}

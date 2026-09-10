import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-notify-owner',
    name: 'Notify workflow owner',
    description: 'Send the person who created this workflow an in-app notification and a push to their devices.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.title)) {
  throw Error('Title is required')
}

let payload := { 'title': inputs.title, 'body': inputs.body ?? '' }

if (not empty(inputs.task_id)) {
  payload.task_id := inputs.task_id
}

let response := postHogNotifyOwner(payload)

if (response.status >= 400) {
  throw Error(f'Failed to notify the workflow owner ({response.status}): {apiErrorMessage(response)}')
}
`,
    inputs_schema: [
        {
            key: 'title',
            type: 'string',
            label: 'Title',
            secret: false,
            required: true,
            description: 'Notification title. Supports variable templating.',
        },
        {
            key: 'body',
            type: 'string',
            label: 'Body',
            secret: false,
            required: false,
            description: 'Notification body. Supports variable templating.',
        },
        {
            key: 'task_id',
            type: 'string',
            label: 'Task',
            secret: false,
            required: false,
            description:
                'Task the notification opens, usually the id of a "Create AI task" step read through an output variable.',
        },
    ],
}

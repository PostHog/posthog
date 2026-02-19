import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-update-ticket',
    name: 'Update conversation ticket',
    description: 'Update the status, priority, or assignee of a conversation ticket',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.ticket_id)) {
  throw Error('Ticket ID is required')
}

let updates := {}

if (not empty(inputs.status) and inputs.status != '') {
  updates.status := inputs.status
}

if (not empty(inputs.priority) and inputs.priority != '') {
  updates.priority := inputs.priority
}

let response := postHogUpdateTicket({
  'ticket_id': inputs.ticket_id,
  'updates': updates
})

if (response.status >= 400) {
  throw Error(f'Failed to update ticket: {response.status}')
}

return response.body
`,
    inputs_schema: [
        {
            key: 'ticket_id',
            type: 'string',
            label: 'Ticket ID',
            secret: false,
            required: true,
            default: '{event.properties.ticket_id}',
            description: 'The UUID of the ticket to update. Available from trigger event properties.',
        },
        {
            key: 'status',
            type: 'choice',
            label: 'Status',
            secret: false,
            required: false,
            choices: [
                { label: 'New', value: 'new' },
                { label: 'Open', value: 'open' },
                { label: 'Pending', value: 'pending' },
                { label: 'On hold', value: 'on_hold' },
                { label: 'Resolved', value: 'resolved' },
            ],
            description: 'New status for the ticket. Leave empty to keep current.',
        },
        {
            key: 'priority',
            type: 'choice',
            label: 'Priority',
            secret: false,
            required: false,
            choices: [
                { label: 'Low', value: 'low' },
                { label: 'Medium', value: 'medium' },
                { label: 'High', value: 'high' },
            ],
            description: 'New priority for the ticket. Leave empty to keep current.',
        },
    ],
}

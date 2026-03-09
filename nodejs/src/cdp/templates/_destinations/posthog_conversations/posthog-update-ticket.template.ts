import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-update-ticket',
    name: 'Update conversation ticket',
    description: 'Update the status, priority, SLA, assignee, or tags of a conversation ticket',
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

if (inputs.sla_amount == 'clear') {
  updates.sla_due_at := null
} else if (not empty(inputs.sla_amount)) {
  let amount := toFloat(inputs.sla_amount)
  let unit := inputs.sla_unit ?? 'hour'

  if (amount == null or amount <= 0) {
    throw Error(f'Invalid SLA amount: {inputs.sla_amount}. Must be a positive number or "clear".')
  }
  let deadline := dateAdd(unit, amount, now())
  updates.sla_due_at := formatDateTime(deadline, '%Y-%m-%dT%H:%i:%SZ')
}

if (not empty(inputs.assignee)) {
  updates.assignee := inputs.assignee
}

if (not empty(inputs.tags)) {
  updates.tags := inputs.tags
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
        {
            key: 'sla_amount',
            type: 'string',
            label: 'SLA deadline',
            secret: false,
            required: false,
            description: 'Duration from now until SLA expires. Set to "clear" to remove the SLA.',
        },
        {
            key: 'sla_unit',
            type: 'choice',
            label: 'SLA unit',
            secret: false,
            required: false,
            default: 'hour',
            choices: [
                { label: 'Minute(s)', value: 'minute' },
                { label: 'Hour(s)', value: 'hour' },
                { label: 'Day(s)', value: 'day' },
            ],
            description: 'Time unit for the SLA deadline.',
        },
        {
            key: 'assignee',
            type: 'posthog_assignee',
            label: 'Assignee',
            secret: false,
            required: false,
            description: 'Assign ticket to a user or role. Leave empty to keep current assignment.',
        },
        {
            key: 'tags',
            type: 'posthog_ticket_tags',
            label: 'Tags',
            secret: false,
            required: false,
            description: 'Set tags on the ticket. Leave empty to keep current tags.',
        },
    ],
}

import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-record-ticket-email',
    name: 'Record email on conversation ticket',
    description:
        'Note on a ticket that this workflow emailed the customer, so agents can see it in the ticket activity.',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.ticket_id)) {
  throw Error('Ticket ID is required')
}

if (empty(inputs.recipient)) {
  throw Error('Recipient is required')
}

let response := postHogRecordTicketEmail({
  'ticket_id': inputs.ticket_id,
  'recipient': inputs.recipient,
  'subject': inputs.subject
})

if (response.status >= 400) {
  throw Error(f'Failed to record ticket email: {response.status}')
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
            description: 'The UUID of the ticket the email was about. Available from trigger event properties.',
        },
        {
            key: 'recipient',
            type: 'string',
            label: 'Recipient',
            secret: false,
            required: true,
            default: '{person.properties.email}',
            description: 'The address the email was sent to.',
        },
        {
            key: 'subject',
            type: 'string',
            label: 'Subject',
            secret: false,
            required: false,
            description: 'The subject line that was sent, shown in the ticket activity.',
        },
    ],
}

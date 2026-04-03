import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-get-ticket',
    name: 'Get conversation ticket',
    description: 'Fetch current ticket data into a workflow variable',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
if (empty(inputs.ticket_id)) {
  throw Error('Ticket ID is required')
}

let response := postHogGetTicket({'ticket_id': inputs.ticket_id})

if (response.status != 200) {
  throw Error(f'Failed to fetch ticket: {response.status}')
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
            description: 'The UUID of the ticket to fetch. Available from trigger event properties.',
        },
    ],
}

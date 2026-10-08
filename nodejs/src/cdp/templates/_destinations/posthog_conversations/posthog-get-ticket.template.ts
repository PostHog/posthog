import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

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
${hogApiErrorMessageFn}

if (empty(inputs.ticket_id)) {
  throw Error('Ticket ID is required')
}

let response := postHogGetTicket({
  'ticket_id': inputs.ticket_id,
  'include_first_customer_message_text': inputs.include_first_customer_message_text
})

if (response.status != 200) {
  throw Error(f'Failed to fetch ticket ({response.status}): {apiErrorMessage(response)}')
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
        {
            key: 'include_first_customer_message_text',
            type: 'boolean',
            label: 'Include first customer message text',
            secret: false,
            required: false,
            default: false,
            description:
                "Add a short preview of the customer's first message to the response. Off by default, since it runs an extra query. Turn it on to remind the customer which ticket a message is about.",
        },
    ],
}

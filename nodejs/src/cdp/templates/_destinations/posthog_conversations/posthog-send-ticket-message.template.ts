import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-send-ticket-message',
    name: 'Send conversation ticket message',
    description: 'Post a reply on a ticket, or save it as a private note',
    icon_url: '/static/posthog-icon.svg',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.ticket_id)) {
  throw Error('Ticket ID is required')
}

if (empty(inputs.message)) {
  throw Error('Message is required')
}

let response := postHogSendTicketMessage({
  'ticket_id': inputs.ticket_id,
  'message': inputs.message,
  'is_private': inputs.is_private
})

if (response.status >= 400) {
  throw Error(f'Failed to send message ({response.status}): {apiErrorMessage(response)}')
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
            description: 'The UUID of the ticket to post on. Available from trigger event properties.',
        },
        {
            key: 'message',
            type: 'string',
            label: 'Message',
            secret: false,
            required: true,
            description: 'Text to post on the ticket. You can use variables.',
        },
        {
            key: 'is_private',
            type: 'boolean',
            label: 'Send as a private note',
            secret: false,
            required: false,
            default: false,
            description:
                'Keep this message internal. The customer does not see it, and it is not delivered on the ticket channel.',
        },
    ],
}

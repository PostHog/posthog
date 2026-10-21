import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-slack-dm-ticket-assignee',
    name: 'Message ticket assignee on Slack',
    description: "Send a Slack direct message to the ticket's assignee",
    icon_url: '/static/services/slack.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

if (empty(inputs.ticket_id)) {
  throw Error('Ticket ID is required')
}

if (empty(inputs.text)) {
  throw Error('Message is required')
}

let response := postHogSlackDmTicketAssignee({
  'ticket_id': inputs.ticket_id,
  'integration_id': inputs.slack_workspace.$integration_id,
  'text': inputs.text
})

if (response.status >= 400) {
  throw Error(f'Failed to message the assignee ({response.status}): {apiErrorMessage(response)}')
}

// An unassigned ticket is a normal state, not a failure, so the step finishes without a message.
if (response.body.outcome == 'unassigned') {
  print('The ticket has no assignee, so no Slack message was sent.')
}

return response.body
`,
    inputs_schema: [
        {
            key: 'slack_workspace',
            type: 'integration',
            integration: 'slack',
            label: 'Slack workspace',
            requiredScopes: 'chat:write users:read users:read.email',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'ticket_id',
            type: 'string',
            label: 'Ticket ID',
            secret: false,
            required: true,
            default: '{event.properties.ticket_id}',
            description:
                'The UUID of the ticket whose assignee gets the message. Available from trigger event properties.',
        },
        {
            key: 'text',
            type: 'string',
            label: 'Message',
            secret: false,
            required: true,
            default: 'Ticket #{event.properties.ticket_number} needs your attention.',
            description:
                'Text of the direct message. You can use variables and Slack formatting such as *bold*. Links and mentions show as plain text. A button that opens the ticket is added below it.',
        },
    ],
}

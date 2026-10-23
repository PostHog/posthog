import { HogFunctionTemplate } from '~/cdp/types'

import { hogApiErrorMessageFn } from '../../hog-helpers'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-posthog-slack-dm-team-member',
    name: 'Message team member on Slack',
    description: 'Send a Slack direct message to a member of your PostHog team.',
    icon_url: '/static/services/slack.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
${hogApiErrorMessageFn}

let response := postHogSlackDmTeamMember({
  'integration_id': inputs.slack_workspace.$integration_id,
  'recipient': inputs.recipient,
  'text': inputs.text,
  'button_url': inputs.button_url,
  'button_text': inputs.button_text
})

if (response.status >= 400) {
  throw Error(f'Could not message the team member on Slack ({response.status}): {apiErrorMessage(response)}')
}

print(response.body.detail)
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
            key: 'recipient',
            type: 'string',
            label: 'Team member',
            secret: false,
            required: true,
            description:
                'Email address or PostHog user ID of the person to message. They must be a member of this project. You can use variables, for example {variables.ticket_assignee.user.email} after a Get ticket step. If the value is empty, the step finishes without sending.',
        },
        {
            key: 'text',
            type: 'string',
            label: 'Message',
            secret: false,
            required: true,
            description:
                'Text of the direct message. You can use variables and Slack formatting such as *bold*. Links and mentions show as plain text, so use the button for a link.',
        },
        {
            key: 'button_url',
            type: 'string',
            label: 'Button link',
            secret: false,
            required: false,
            description:
                'Adds a button below the message that opens this link. The link must start with http:// or https://.',
        },
        {
            key: 'button_text',
            type: 'string',
            label: 'Button label',
            secret: false,
            required: false,
            default: 'Open',
            description: 'Text on the button.',
        },
    ],
}

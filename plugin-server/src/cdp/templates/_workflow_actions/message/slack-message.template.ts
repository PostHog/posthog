import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'hidden',
    type: 'destination',
    id: 'template-hogflow-send-message-slack',
    name: 'Slack Message',
    description: 'Send messages from Workflows to Slack channels or users',
    icon_url: '/static/services/slack.png',
    category: ['Communication'],
    hog: `
let slackConfig := inputs.slack_config
let channel := inputs.channel
let message := inputs.message

if (not channel) {
    throw Error('Slack channel is required')
}

if (not message) {
    throw Error('Message is required')
}

let payload := {
    'channel': channel,
    'text': message,
    'username': inputs.username or 'PostHog',
    'icon_emoji': inputs.icon_emoji or ':hedgehog:',
    'unfurl_links': inputs.unfurl_links or false,
    'unfurl_media': inputs.unfurl_media or false
}

if (inputs.blocks) {
    payload.blocks := inputs.blocks
}

if (inputs.attachments) {
    payload.attachments := inputs.attachments
}

if (inputs.debug) {
    print('Sending Slack message', payload)
}

// Use the Slack config from the integration
let res := fetch('https://slack.com/api/chat.postMessage', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {slackConfig.access_token}',
        'Content-Type': 'application/json'
    },
    'body': payload
});

if (res.status != 200 or res.body.ok == false) {
  throw Error(f'Failed to post message to Slack: {res.status}: {res.body}');
}

if (inputs.debug) {
    print('Slack message sent', res)
}
`,
    inputs_schema: [
        {
            key: 'slack_config',
            type: 'integration',
            integration: 'slack',
            label: 'Slack Configuration',
            secret: false,
            required: true,
            description: 'Slack workspace configuration for sending messages.',
        },
        {
            key: 'channel',
            type: 'string',
            label: 'Channel',
            secret: false,
            required: true,
            description: 'Slack channel ID or name (e.g., #general or @username).',
            default: '#general',
        },
        {
            key: 'message',
            type: 'string',
            label: 'Message',
            secret: false,
            required: true,
            description: 'Message content to send to Slack.',
            default: 'PostHog event {event.event} was triggered by {person.properties.email or "Unknown user"}',
        },
        {
            key: 'username',
            type: 'string',
            label: 'Bot Username',
            secret: false,
            required: false,
            default: 'PostHog',
            description: 'Username for the bot sending the message.',
        },
        {
            key: 'icon_emoji',
            type: 'string',
            label: 'Bot Icon Emoji',
            secret: false,
            required: false,
            default: ':hedgehog:',
            description: 'Emoji to use as the bot icon.',
        },
        {
            key: 'blocks',
            type: 'json',
            label: 'Blocks',
            secret: false,
            required: false,
            description: 'Slack Block Kit blocks for rich message formatting.',
        },
        {
            key: 'attachments',
            type: 'json',
            label: 'Attachments',
            secret: false,
            required: false,
            description: 'Legacy Slack message attachments.',
        },
        {
            key: 'unfurl_links',
            type: 'boolean',
            label: 'Unfurl Links',
            secret: false,
            required: false,
            default: false,
            description: 'Automatically unfurl links in the message.',
        },
        {
            key: 'unfurl_media',
            type: 'boolean',
            label: 'Unfurl Media',
            secret: false,
            required: false,
            default: false,
            description: 'Automatically unfurl media links in the message.',
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the Slack API responses for debugging.',
            secret: false,
            required: false,
            default: false,
        },
    ],
}

import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'stable',
    free: true,
    type: 'destination',
    id: 'template-slack',
    name: 'Slack',
    description: 'Sends a message to a Slack channel',
    icon_url: '/static/services/slack.png',
    category: ['Customer Success'],
    code_language: 'hog',
    code: `
let body := {
  'channel': inputs.channel,
  'blocks': inputs.blocks,
  'text': inputs.text
};

// Slack rejects an empty thread_ts, so only send it when there is one to reply under.
if (not empty(inputs.thread_ts)) {
  body['thread_ts'] := inputs.thread_ts;
}

// Slack refuses the whole message when these two are present without chat:write.customize, and both
// carry a default, so drop them when the connection records a scope list that lacks it. An install
// with no recorded scopes keeps its customization, matching what the config UI reports.
let granted := replaceAll(inputs.slack_workspace.scope ?? '', ' ', '');
let can_customize := empty(granted) or has(splitByString(',', granted), 'chat:write.customize');

if (can_customize and not empty(inputs.icon_emoji)) {
  body['icon_emoji'] := inputs.icon_emoji;
}

if (can_customize and not empty(inputs.username)) {
  body['username'] := inputs.username;
}

let res := fetch('https://slack.com/api/chat.postMessage', {
  'body': body,
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.slack_workspace.access_token}',
    'Content-Type': 'application/json'
  }
});

if (res.status != 200 or res.body.ok == false) {
  throw Error(f'Failed to post message to Slack: {res.status}: {res.body}');
}
`.trim(),
    inputs_schema: [
        {
            key: 'slack_workspace',
            type: 'integration',
            integration: 'slack',
            label: 'Slack workspace',
            requiredScopes: 'chat:write',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'channel',
            type: 'integration_field',
            integration_key: 'slack_workspace',
            integration_field: 'slack_channel',
            requiredScopes: 'channels:read groups:read',
            label: 'Channel to post to',
            description:
                'Select the channel to post to. Channel IDs (e.g. C0123ABC, returned by integrations-channels-retrieve) are preferred; #channel-name (e.g. #general) is also accepted. The PostHog app must be installed in the workspace. For private channels, the PostHog app must be a member of the channel.',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'icon_emoji',
            type: 'string',
            label: 'Emoji icon',
            integration_key: 'slack_workspace',
            requiredScopes: 'chat:write.customize',
            default: ':hedgehog:',
            required: false,
            secret: false,
            hidden: false,
        },
        {
            key: 'username',
            type: 'string',
            label: 'Bot name',
            integration_key: 'slack_workspace',
            requiredScopes: 'chat:write.customize',
            default: 'PostHog',
            required: false,
            secret: false,
            hidden: false,
        },
        {
            key: 'blocks',
            type: 'json',
            label: 'Blocks',
            description: '(see https://api.slack.com/block-kit/building)',
            default: [
                {
                    text: {
                        text: "*{person.name}* triggered event: '{event.event}'",
                        type: 'mrkdwn',
                    },
                    type: 'section',
                },
                {
                    type: 'actions',
                    elements: [
                        {
                            url: '{person.url}',
                            text: { text: 'View Person in PostHog', type: 'plain_text' },
                            type: 'button',
                        },
                        {
                            url: '{source.url}',
                            text: { text: 'Message source', type: 'plain_text' },
                            type: 'button',
                        },
                    ],
                },
            ],
            secret: false,
            required: false,
            hidden: false,
        },
        {
            key: 'text',
            type: 'string',
            label: 'Plain text message',
            description: 'Optional fallback message if blocks are not provided or supported',
            default: "*{person.name}* triggered event: '{event.event}'",
            secret: false,
            required: false,
            hidden: false,
        },
        {
            key: 'thread_ts',
            type: 'string',
            label: 'Reply in thread',
            description:
                'Timestamp of the message to reply under. Leave this empty to post a new message. In a workflow triggered by a Slack message, use {event.properties.thread_ts ?? event.properties.ts} to reply under the message that started the run.',
            secret: false,
            required: false,
            hidden: false,
        },
    ],
}

import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    status: 'beta',
    free: true,
    type: 'destination',
    id: 'template-microsoft-teams-channel',
    name: 'Microsoft Teams channel',
    description: 'Posts a message to a Microsoft Teams channel, or replies in a thread, as the connected Microsoft user',
    icon_url: '/static/services/microsoft-teams.png',
    category: ['Customer Success'],
    code_language: 'hog',
    code: `
let url := f'https://graph.microsoft.com/v1.0/teams/{encodeURLComponent(inputs.team)}/channels/{encodeURLComponent(inputs.channel)}/messages';

if (not empty(inputs.reply_to_message_id)) {
  url := f'{url}/{encodeURLComponent(inputs.reply_to_message_id)}/replies';
}

let res := fetch(url, {
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.microsoft_teams.access_token}',
    'Content-Type': 'application/json'
  },
  'body': {
    'body': {
      'contentType': inputs.content_type ?? 'html',
      'content': inputs.message
    }
  }
});

if (res.status < 200 or res.status >= 300) {
  throw Error(f'Failed to post message to Microsoft Teams: {res.status}: {res.body}');
}

// message_id is always the thread root, because Graph cannot reply under a reply.
if (empty(inputs.reply_to_message_id)) {
  return {'message_id': res.body.id, 'reply_id': null, 'web_url': res.body.webUrl};
}
return {'message_id': inputs.reply_to_message_id, 'reply_id': res.body.id, 'web_url': res.body.webUrl};
`.trim(),
    inputs_schema: [
        {
            key: 'microsoft_teams',
            type: 'integration',
            integration: 'microsoft-teams',
            label: 'Microsoft Teams account',
            description: 'Messages show as sent by the Microsoft user who connected this account.',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'team',
            type: 'integration_field',
            integration_key: 'microsoft_teams',
            integration_field: 'microsoft_teams_team',
            label: 'Team',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'channel',
            type: 'integration_field',
            integration_key: 'microsoft_teams',
            integration_field: 'microsoft_teams_channel',
            requires_field: 'team',
            label: 'Channel to post to',
            description: 'The connected Microsoft user must be a member of this channel.',
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'message',
            type: 'string',
            label: 'Message',
            default: "<b>{person.name}</b> triggered event: '{event.event}'",
            secret: false,
            hidden: false,
            required: true,
        },
        {
            key: 'content_type',
            type: 'choice',
            label: 'Message format',
            choices: [
                { label: 'HTML', value: 'html' },
                { label: 'Plain text', value: 'text' },
            ],
            default: 'html',
            secret: false,
            hidden: false,
            required: false,
        },
        {
            key: 'reply_to_message_id',
            type: 'string',
            label: 'Reply in thread',
            description:
                'ID of the channel message to reply under. Leave this empty to start a new thread. This step returns the thread ID as message_id, so a later step can reply in the same thread.',
            secret: false,
            hidden: false,
            required: false,
        },
    ],
}

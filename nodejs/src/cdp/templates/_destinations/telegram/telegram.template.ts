import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'stable',
    type: 'destination',
    id: 'template-telegram',
    name: 'Telegram',
    description: 'Send a message to a Telegram chat, group, or channel with a Telegram bot',
    icon_url: '/static/services/telegram.svg',
    category: ['Communication'],
    code_language: 'hog',
    code: `
let botToken := inputs.bot_token
let chatId := inputs.chat_id

if (empty(botToken)) {
    throw Error('Bot token is required')
}

if (empty(chatId)) {
    throw Error('Chat ID is required')
}

if (empty(inputs.text)) {
    throw Error('Message text is required')
}

let body := {
    'chat_id': chatId,
    'text': inputs.text
}

if (inputs.parse_mode == 'HTML' or inputs.parse_mode == 'MarkdownV2') {
    body['parse_mode'] := inputs.parse_mode
}

if (not empty(inputs.message_thread_id)) {
    let threadId := toInt(inputs.message_thread_id)
    if (threadId == null) {
        throw Error(f'Topic ID must be a number, got: {inputs.message_thread_id}')
    }
    body['message_thread_id'] := threadId
}

if (inputs.disable_notification) {
    body['disable_notification'] := true
}

if (inputs.disable_link_preview) {
    body['link_preview_options'] := {
        'is_disabled': true
    }
}

if (inputs.debug) {
    print('Sending Telegram message', body)
}

let res := fetch(f'https://api.telegram.org/bot{botToken}/sendMessage', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status != 200 or res.body.ok != true) {
    throw Error(f'Failed to send Telegram message: {res.status}: {res.body.description}')
}

if (inputs.debug) {
    print('Telegram message sent', res)
}
`,
    inputs_schema: [
        {
            key: 'bot_token',
            type: 'string',
            label: 'Bot token',
            description:
                'The token that @BotFather gives you when you create a bot. Add the bot to the group or channel before you send messages to it.',
            secret: true,
            required: true,
        },
        {
            key: 'chat_id',
            type: 'string',
            label: 'Chat ID',
            description:
                'The ID of the chat, group, or channel that gets the message. For a public channel you can use its username, for example @mychannel. To message a person, store their chat ID as a person property and use it here, for example {person.properties.telegram_chat_id}.',
            secret: false,
            required: true,
        },
        {
            key: 'text',
            type: 'string',
            label: 'Message',
            description: 'The message text. Telegram accepts up to 4096 characters.',
            default: '{person.name} triggered event: {event.event}',
            secret: false,
            required: true,
        },
        {
            key: 'parse_mode',
            type: 'choice',
            label: 'Formatting',
            description:
                'How Telegram formats the message. With HTML or MarkdownV2, Telegram rejects a message that has unescaped special characters, so take care when the message includes event or person values.',
            choices: [
                { label: 'Plain text', value: 'none' },
                { label: 'HTML', value: 'HTML' },
                { label: 'MarkdownV2', value: 'MarkdownV2' },
            ],
            default: 'none',
            secret: false,
            required: false,
        },
        {
            key: 'message_thread_id',
            type: 'string',
            label: 'Topic ID',
            description: 'Sends the message to this topic in a group that has topics turned on.',
            secret: false,
            required: false,
        },
        {
            key: 'disable_notification',
            type: 'boolean',
            label: 'Send silently',
            description: 'Recipients get a notification with no sound.',
            default: false,
            secret: false,
            required: false,
        },
        {
            key: 'disable_link_preview',
            type: 'boolean',
            label: 'Turn off link previews',
            description: 'Telegram does not show a preview for links in the message.',
            default: false,
            secret: false,
            required: false,
        },
        {
            key: 'debug',
            type: 'boolean',
            label: 'Log responses',
            description: 'Logs the Telegram API responses for debugging.',
            default: false,
            secret: false,
            required: false,
        },
    ],
}

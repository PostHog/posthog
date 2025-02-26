import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'transformation',
    id: 'template-bot-detection-ip',
    name: 'Filter Bot Events by IP addresses',
    description:
        'Filters out events from known bot IP addresses. This transformation will drop the event if a bot is detected.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `


return event
    `,
    inputs_schema: [
        {
            key: 'userAgent',
            type: 'string',
            label: 'User Agent Property',
            description: 'The property that contains the user agent string (e.g. $raw_user_agent, $useragent)',
            default: '$raw_user_agent',
            secret: false,
            required: true,
        },
        {
            key: 'customBotPatterns',
            type: 'string',
            label: 'Custom Bot Patterns',
            description: 'Additional bot patterns to detect, separated by commas (e.g. mybot,customcrawler)',
            default: '',
            secret: false,
            required: false,
        },
    ],
}

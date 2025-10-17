import { HogFunctionTemplate } from '~/cdp/types'

export const template: HogFunctionTemplate = {
    free: true,
    status: 'beta',
    type: 'transformation',
    id: 'template-bot-detection',
    name: 'Filter Bot Events',
    description:
        'Filters out events from known bot user agents. This transformation will drop the event if a bot is detected.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    code_language: 'hog',
    code: `
// Get the user agent value
let user_agent := event.properties[inputs.userAgent]

// Check if user agent property exists in event
if (empty(user_agent) and inputs.keepUndefinedUseragent == 'No') {
    return null
}

if (inputs.filterKnownBotUserAgents and isKnownBotUserAgent(user_agent)) {
    return null
}

let bot_list := []

if (notEmpty(inputs.customBotPatterns)) {
    let custom_patterns := splitByString(',', inputs.customBotPatterns)
    // Add each custom pattern to the list
    for (let pattern in custom_patterns) {
        bot_list := arrayPushBack(bot_list, trim(pattern))
    }
}

// If bot is detected, return null to filter out the event
for (let bot_name in bot_list) {
    if (user_agent =~* bot_name) {
        return null
    }
}

let ip := event.properties['$ip']
if (empty(ip)) {
    return event
}

if (inputs.filterKnownBotIps and isKnownBotIp(ip)) {
    return null
}

let bot_ip_prefixes := []

if (inputs.customIpPrefixes and notEmpty(inputs.customIpPrefixes)) {
    let custom_prefixes := splitByString(',', inputs.customIpPrefixes)
    // Add each custom prefix to the list
    for (let prefix in custom_prefixes) {
        if (isIPAddressInRange(ip, trim(prefix))) {
            return null
        }
    }
}

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
            key: 'filterKnownBotUserAgents',
            type: 'boolean',
            label: 'Filter out known bot user agents',
            description:
                "Filter out known bot user agents using PostHog's known bot user agents list. This is kept up to date dynamically.",
            default: true,
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
        {
            key: 'filterKnownBotIps',
            type: 'boolean',
            label: 'Filter out known bot ips',
            description:
                "Filter out known bot ips using PostHog's known bot ips list. This is kept up to date dynamically.",
            default: true,
            secret: false,
            required: true,
        },
        {
            key: 'customIpPrefixes',
            type: 'string',
            label: 'Custom IP Prefixes',
            description:
                'Additional IPv4 or IPv6 prefixes in CIDR notation to block, separated by commas (e.g. 198.51.100.14/24,2001:db8::/48)',
            default: '',
            secret: false,
            required: false,
        },
        {
            key: 'keepUndefinedUseragent',
            type: 'choice',
            label: 'Keep events where the useragent is not set?',
            description:
                'Some events such as server-side events may not have a useragent property, choose if you want to keep these events',
            default: 'Yes',
            secret: false,
            required: false,
            choices: [
                { value: 'Yes', label: 'Yes' },
                { value: 'No', label: 'No' },
            ],
        },
    ],
}

import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'transformation',
    id: 'template-bot-detection',
    name: 'Filter Bot Events',
    description:
        'Filters out events from known bot user agents. This transformation will drop the event if a bot is detected.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
// List of known bot user agents
let known_bot_filter_list := [
    'bot', 'crawler', 'spider', 'feedfetcher-google', 'mediapartners-google', 
    'apis-google', 'slurp', 'python-urllib', 'python-requests', 'aiohttp', 
    'httpx', 'libwww-perl', 'httpunit', 'nutch', 'go-http-client', 'biglotron', 
    'teoma', 'convera', 'gigablast', 'ia_archiver', 'webmon ', 'httrack', 
    'grub.org', 'netresearchserver', 'speedy', 'fluffy', 'findlink', 'panscient', 
    'ips-agent', 'yanga', 'yandex', 'yadirectfetcher', 'cyberpatrol', 'postrank', 
    'page2rss', 'linkdex', 'ezooms', 'heritrix', 'findthatfile', 'europarchive.org', 
    'mappydata', 'eright', 'apercite', 'aboundex', 'summify', 'ec2linkfinder', 
    'facebookexternalhit', 'yeti', 'retrevopageanalyzer', 'sogou', 'wotbox', 
    'ichiro', 'drupact', 'coccoc', 'integromedb', 'siteexplorer.info', 'proximic', 
    'changedetection', 'cc metadata scaper', 'g00g1e.net', 'binlar', 'a6-indexer', 
    'admantx', 'megaindex', 'ltx71', 'bubing', 'qwantify', 'lipperhey', 'addthis'
]

let userAgentProperty := lower(inputs.userAgent)

// Check if user agent exists
if (empty(event.properties[userAgentProperty])) {
    return event
}

// Convert user agent to lower case for case-insensitive comparison
let user_agent := lower(event.properties[userAgentProperty])

// Function to check if user agent contains any bot identifier
fun isBot(ua) {
    for (let bot_name in known_bot_filter_list) {
        if (ua =~* bot_name) {
            return true
        }
    }
    return false
}

// If bot is detected, return null to filter out the event
// Otherwise return the original event
if (isBot(user_agent)) {
    return null
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
    ],
}

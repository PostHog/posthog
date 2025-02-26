import { HogFunctionTemplate } from '../../types'

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'transformation',
    id: 'template-bot-detection',
    name: 'Filter Bot Events by UserAgent',
    description:
        'Filters out events from known bot user agents. This transformation will drop the event if a bot is detected.',
    icon_url: '/static/hedgehog/builder-hog-01.png',
    category: ['Custom'],
    hog: `
// List of known bot user agents
let known_bot_filter_list := ['bot', 'crawler', 'spider', 'feedfetcher-google',
'mediapartners-google', 'apis-google', 'slurp', 'python-urllib',
'python-requests', 'aiohttp', 'httpx', 'libwww-perl',
'httpunit', 'nutch', 'go-http-client', 'biglotron', 'teoma',
'convera', 'gigablast', 'ia_archiver', 'webmon ', 'httrack',
'grub.org', 'netresearchserver', 'speedy', 'fluffy',
'findlink', 'panscient', 'ips-agent', 'yanga', 'yandex',
'yadirectfetcher', 'cyberpatrol', 'postrank', 'page2rss',
'linkdex', 'ezooms', 'heritrix', 'findthatfile', 'europarchive.org',
'mappydata', 'eright', 'apercite', 'aboundex', 'summify', 'ec2linkfinder',
'facebookexternalhit', 'yeti', 'retrevopageanalyzer', 'sogou', 'wotbox',
'ichiro', 'drupact', 'coccoc', 'integromedb', 'siteexplorer.info',
'proximic', 'changedetection', 'cc metadata scaper', 'g00g1e.net',
'binlar', 'a6-indexer', 'admantx', 'megaindex', 'ltx71', 'bubing',
'qwantify', 'lipperhey', 'addthis', 'metauri', 'scrapy', 'capsulechecker',
'sonic', 'sysomos', 'trove', 'deadlinkchecker', 'slack-imgproxy', 'embedly',
'iskanie', 'skypeuripreview', 'google-adwords-instant', 'whatsapp',
'electricmonk', 'yahoo link preview', 'xenu link sleuth', 'pcore-http',
'appinsights', 'phantomjs', 'jetslide', 'newsharecounts', 'tineye',
'linkarchiver', 'digg deeper', 'snacktory', 'okhttp', 'nuzzel', 'omgili',
'pocketparser', 'um-ln', 'muckrack', 'netcraftsurveyagent', 'appengine-google',
'jetty', 'upflow', 'thinklab', 'traackr.com', 'twurly', 'mastodon', 'http_get',
'brandverity', 'check_http', 'ezid', 'genieo', 'meltwaternews', 'moreover',
'scoutjet', 'seoscanners', 'hatena', 'google web preview', 'adscanner',
'netvibes', 'baidu-yunguance', 'btwebclient', 'disqus', 'feedly', 'fever',
'flamingo_searchengine', 'flipboardproxy', 'g2 web services', 'vkshare',
'siteimprove.com', 'dareboost', 'feedspot', 'seokicks', 'tracemyfile',
'zgrab', 'pr-cy.ru', 'datafeedwatch', 'zabbix', 'google-xrawler', 'axios',
'amazon cloudfront', 'pulsepoint', 'cloudflare-alwaysonline',
'google-structured-data-testing-tool', 'wordupinfosearch', 'webdatastats',
'httpurlconnection', 'outbrain', 'w3c_validator', 'w3c-checklink',
'w3c-mobileok', 'w3c_i18n-checker', 'feedvalidator', 'w3c_css_validator',
'w3c_unicorn', 'google-physicalweb', 'blackboard', 'bazqux', 'twingly',
'rivva', 'dataprovider.com', 'theoldreader.com', 'anyevent',
'nmap scripting engine', '2ip.ru', 'clickagy', 'google favicon',
'hubspot', 'chrome-lighthouse', 'headlesschrome', 'simplescraper',
'fedoraplanet', 'friendica', 'nextcloud', 'tiny tiny rss', 'datanyze',
'google-site-verification', 'trendsmapresolver', 'tweetedtimes', 'gwene',
'simplepie', 'searchatlas', 'superfeedr', 'freewebmonitoring sitechecker',
'pandalytics', 'seewithkids', 'cincraw', 'freshrss', 'google-certificates-bridge',
'viber', 'evc-batch', 'virustotal', 'uptime-kuma', 'feedbin',
'snap url preview service', 'ruxitsynthetic', 'google-read-aloud',
'mediapartners', 'wget', 'wget', 'ahrefsgot', 'ahrefssiteaudit',
'wesee:search', 'y!j', 'collection@infegy.com', 'deusu', 'bingpreview',
'daum', 'pingdom', 'barkrowler', 'yak', 'ning', 'ahc', 'apache-httpclient',
'buck', 'newspaper', 'sentry', 'fetch', 'miniflux', 'validator.nu',
'grouphigh', 'checkmarknetwork', 'www.uptime.com', 'mixnodecache',
'domains project', 'pagepeeker', 'vigil', 'php-curl-class', 'ptst',
'seostar.co']

let userAgentProperty := inputs.userAgent

// Check if user agent property exists in event
// We treat missing user agent as bot traffic
if (empty(event.properties[userAgentProperty])) {
    return null
}

// Get the user agent value
let user_agent := event.properties[userAgentProperty]

// Check for empty string
// We treat empty user agent as bot traffic
if (user_agent == '') {
    return null
}

// Now that we know we have a valid user agent, convert to lower case
user_agent := lower(user_agent)

// Handle custom bot patterns
let bot_list := known_bot_filter_list
if (notEmpty(inputs.customBotPatterns)) {
    let custom_patterns := splitByString(',', inputs.customBotPatterns)
    // Add each custom pattern to the list
    for (let pattern in custom_patterns) {
        bot_list := arrayPushBack(bot_list, trim(pattern))
    }
}

// Function to check if user agent contains any bot identifier
fun isBot(ua) {
    for (let bot_name in bot_list) {
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

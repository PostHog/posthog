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
fun isBotUa(ua) {
    for (let bot_name in bot_list) {
        if (ua =~* bot_name) {
            return true
        }
    }
    return false
}

// If bot is detected, return null to filter out the event
// Otherwise return the original event
if (isBotUa(user_agent)) {
    return null
}

let known_bot_ip_prefixes := [
  // ahrefs
  '5.39.1.224/27',
  '5.39.109.160/27',
  '15.235.27.0/24',
  '15.235.96.0/24',
  '15.235.98.0/24',
  '37.59.204.128/27',
  '51.68.247.192/27',
  '51.75.236.128/27',
  '51.89.129.0/24',
  '51.161.37.0/24',
  '51.161.65.0/24',
  '51.195.183.0/24',
  '51.195.215.0/24',
  '51.195.244.0/24',
  '51.222.95.0/24',
  '51.222.168.0/24',
  '51.222.253.0/26',
  '54.36.148.0/23',
  '54.37.118.64/27',
  '54.38.147.0/24',
  '54.39.0.0/24',
  '54.39.6.0/24',
  '54.39.89.0/24',
  '54.39.136.0/24',
  '54.39.203.0/24',
  '54.39.210.0/24',
  '92.222.104.192/27',
  '92.222.108.96/27',
  '94.23.188.192/27',
  '142.44.220.0/24',
  '142.44.225.0/24',
  '142.44.228.0/24',
  '142.44.233.0/24',
  '148.113.128.0/24',
  '148.113.130.0/24',
  '167.114.139.0/24',
  '168.100.149.0/24',
  '176.31.139.0/27',
  '198.244.168.0/24',
  '198.244.183.0/24',
  '198.244.186.193/32',
  '198.244.186.194/31',
  '198.244.186.196/30',
  '198.244.186.200/31',
  '198.244.186.202/32',
  '198.244.226.0/24',
  '198.244.240.0/24',
  '198.244.242.0/24',
  '202.8.40.0/22',
  '202.94.84.110/31',
  '202.94.84.112/31',

  // bing
  '157.55.39.0/24',
  '207.46.13.0/24',
  '40.77.167.0/24',
  '13.66.139.0/24',
  '13.66.144.0/24',
  '52.167.144.0/24',
  '13.67.10.16/28',
  '13.69.66.240/28',
  '13.71.172.224/28',
  '139.217.52.0/28',
  '191.233.204.224/28',
  '20.36.108.32/28',
  '20.43.120.16/28',
  '40.79.131.208/28',
  '40.79.186.176/28',
  '52.231.148.0/28',
  '20.79.107.240/28',
  '51.105.67.0/28',
  '20.125.163.80/28',
  '40.77.188.0/22',
  '65.55.210.0/24',
  '199.30.24.0/23',
  '40.77.202.0/24',
  '40.77.139.0/25',
  '20.74.197.0/28',
  '20.15.133.160/27',
  '40.77.177.0/24',
  '40.77.178.0/23',

  // google
  '8.8.4.0/24',
  '8.8.8.0/24',
  '8.34.208.0/20',
  '8.35.192.0/20',
  '23.236.48.0/20',
  '23.251.128.0/19',
  '34.0.0.0/15',
  '34.2.0.0/16',
  '34.3.0.0/23',
  '34.3.3.0/24',
  '34.3.4.0/24',
  '34.3.8.0/21',
  '34.3.16.0/20',
  '34.3.32.0/19',
  '34.3.64.0/18',
  '34.4.0.0/14',
  '34.8.0.0/13',
  '34.16.0.0/12',
  '34.32.0.0/11',
  '34.64.0.0/10',
  '34.128.0.0/10',
  '35.184.0.0/13',
  '35.192.0.0/14',
  '35.196.0.0/15',
  '35.198.0.0/16',
  '35.199.0.0/17',
  '35.199.128.0/18',
  '35.200.0.0/13',
  '35.208.0.0/12',
  '35.224.0.0/12',
  '35.240.0.0/13',
  '57.140.192.0/18',
  '64.15.112.0/20',
  '64.233.160.0/19',
  '66.22.228.0/23',
  '66.102.0.0/20',
  '66.249.64.0/19',
  '70.32.128.0/19',
  '72.14.192.0/18',
  '74.125.0.0/16',
  '104.154.0.0/15',
  '104.196.0.0/14',
  '104.237.160.0/19',
  '107.167.160.0/19',
  '107.178.192.0/18',
  '108.59.80.0/20',
  '108.170.192.0/18',
  '108.177.0.0/17',
  '130.211.0.0/16',
  '136.22.160.0/20',
  '136.22.176.0/21',
  '136.22.184.0/23',
  '136.22.186.0/24',
  '136.124.0.0/15',
  '142.250.0.0/15',
  '146.148.0.0/17',
  '152.65.208.0/22',
  '152.65.214.0/23',
  '152.65.218.0/23',
  '152.65.222.0/23',
  '152.65.224.0/19',
  '162.120.128.0/17',
  '162.216.148.0/22',
  '162.222.176.0/21',
  '172.110.32.0/21',
  '172.217.0.0/16',
  '172.253.0.0/16',
  '173.194.0.0/16',
  '173.255.112.0/20',
  '192.158.28.0/22',
  '192.178.0.0/15',
  '193.186.4.0/24',
  '199.36.154.0/23',
  '199.36.156.0/24',
  '199.192.112.0/22',
  '199.223.232.0/21',
  '207.223.160.0/20',
  '208.65.152.0/22',
  '208.68.108.0/22',
  '208.81.188.0/22',
  '208.117.224.0/19',
  '209.85.128.0/17',
  '216.58.192.0/19',
  '216.73.80.0/20',
  '216.239.32.0/19',
  '2001:4860::/32',
  '2404:6800::/32',
  '2404:f340::/32',
  '2600:1900::/28',
  '2605:ef80::/32',
  '2606:40::/32',
  '2606:73c0::/32',
  '2607:1c0:241:40::/60',
  '2607:1c0:300::/40',
  '2607:f8b0::/32',
  '2620:11a:a000::/40',
  '2620:120:e000::/40',
  '2800:3f0::/32',
  '2a00:1450::/32',
  '2c0f:fb50::/32',
];

if (inputs.customIpPrefixes and notEmpty(inputs.customIpPrefixes)) {
    let custom_prefixes := splitByString(',', inputs.customIpPrefixes)
    // Add each custom prefix to the list
    for (let prefix in custom_prefixes) {
        known_bot_ip_prefixes := arrayPushBack(known_bot_ip_prefixes, trim(prefix))
    }
}

let ip := event.properties['$ip']
if (notEmpty(ip)) {
  for (let prefix in known_bot_ip_prefixes) {
    if (isIPAddressInRange(ip, prefix)) {
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
            key: 'customBotPatterns',
            type: 'string',
            label: 'Custom Bot Patterns',
            description: 'Additional bot patterns to detect, separated by commas (e.g. mybot,customcrawler)',
            default: '',
            secret: false,
            required: false,
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
    ],
}

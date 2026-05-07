/**
 * Client-side bot detection — mirrors `posthog.hogql_queries.web_analytics.bot_definitions`
 * and the `__preview_getBotName` / `__preview_isBot` / `__preview_getTrafficCategory`
 * HogQL functions. Used by real-time dashboards where events arrive via the
 * livestream SSE feed and therefore cannot be classified server-side.
 *
 * Keep this file in sync with `posthog/hogql_queries/web_analytics/bot_definitions.py`.
 */

export type BotTrafficType = 'AI Agent' | 'Bot' | 'Automation' | 'Regular'

export type BotCategory =
    | 'ai_crawler'
    | 'ai_search'
    | 'ai_assistant'
    | 'search_crawler'
    | 'seo_crawler'
    | 'social_crawler'
    | 'monitoring'
    | 'http_client'
    | 'headless_browser'
    | 'no_user_agent'
    | 'regular'

export interface BotDefinition {
    name: string
    category: BotCategory
    trafficType: BotTrafficType
    operator: string
}

// Ordered by specificity — more specific patterns (e.g. `Applebot-Extended`)
// must precede less specific patterns (`Applebot/`).
export const BOT_DEFINITIONS: { pattern: string; definition: BotDefinition }[] = [
    // AI Crawlers (training data collection)
    {
        pattern: 'GPTBot',
        definition: { name: 'GPTBot', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'OpenAI' },
    },
    {
        pattern: 'Google-CloudVertexBot',
        definition: {
            name: 'Google Cloud Vertex',
            category: 'ai_crawler',
            trafficType: 'AI Agent',
            operator: 'Google',
        },
    },
    {
        pattern: 'Google-Extended',
        definition: { name: 'Google AI', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Google' },
    },
    {
        pattern: 'GoogleOther',
        definition: { name: 'GoogleOther', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Google' },
    },
    {
        pattern: 'Claude-SearchBot',
        definition: { name: 'Claude Search', category: 'ai_search', trafficType: 'AI Agent', operator: 'Anthropic' },
    },
    {
        pattern: 'Claude-User',
        definition: { name: 'Claude User', category: 'ai_assistant', trafficType: 'AI Agent', operator: 'Anthropic' },
    },
    {
        pattern: 'ClaudeBot',
        definition: { name: 'Claude', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Anthropic' },
    },
    {
        pattern: 'Claude-Web',
        definition: { name: 'Claude Web', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Anthropic' },
    },
    {
        pattern: 'anthropic-ai',
        definition: { name: 'Anthropic', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Anthropic' },
    },
    {
        pattern: 'Perplexity-User',
        definition: {
            name: 'Perplexity User',
            category: 'ai_assistant',
            trafficType: 'AI Agent',
            operator: 'Perplexity',
        },
    },
    {
        pattern: 'PerplexityBot',
        definition: { name: 'Perplexity', category: 'ai_search', trafficType: 'AI Agent', operator: 'Perplexity' },
    },
    {
        pattern: 'CCBot',
        definition: { name: 'Common Crawl', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Common Crawl' },
    },
    {
        pattern: 'meta-externalagent',
        definition: { name: 'Meta AI', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Meta' },
    },
    {
        pattern: 'Bytespider',
        definition: { name: 'ByteDance', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'ByteDance' },
    },
    {
        pattern: 'TikTokSpider',
        definition: { name: 'TikTok AI', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'ByteDance' },
    },
    {
        pattern: 'cohere-ai',
        definition: { name: 'Cohere', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Cohere' },
    },
    {
        pattern: 'Diffbot',
        definition: { name: 'Diffbot', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Diffbot' },
    },
    {
        pattern: 'omgili',
        definition: { name: 'Webz.io', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Webz.io' },
    },
    {
        pattern: 'Webzio-Extended',
        definition: { name: 'Webz.io Extended', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Webz.io' },
    },
    {
        pattern: 'Timpibot',
        definition: { name: 'Timpi', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Timpi' },
    },
    {
        pattern: 'Amazonbot',
        definition: { name: 'Amazon', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Amazon' },
    },
    {
        pattern: 'PetalBot',
        definition: { name: 'Petal', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Huawei' },
    },
    {
        pattern: 'Brightbot',
        definition: { name: 'Brightbot', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Bright Data' },
    },
    // AI Search (search result generation)
    {
        pattern: 'OAI-SearchBot',
        definition: { name: 'OpenAI Search', category: 'ai_search', trafficType: 'AI Agent', operator: 'OpenAI' },
    },
    {
        pattern: 'Applebot-Extended',
        definition: { name: 'Apple AI', category: 'ai_search', trafficType: 'AI Agent', operator: 'Apple' },
    },
    // AI Assistants (real-time user-facing fetching)
    {
        pattern: 'ChatGPT-User',
        definition: { name: 'ChatGPT', category: 'ai_assistant', trafficType: 'AI Agent', operator: 'OpenAI' },
    },
    {
        pattern: 'Meta-ExternalFetcher',
        definition: { name: 'Meta Fetcher', category: 'ai_assistant', trafficType: 'AI Agent', operator: 'Meta' },
    },
    {
        pattern: 'DuckAssistBot',
        definition: {
            name: 'DuckDuckGo AI',
            category: 'ai_assistant',
            trafficType: 'AI Agent',
            operator: 'DuckDuckGo',
        },
    },
    {
        pattern: 'MistralAI-User',
        definition: { name: 'Mistral AI', category: 'ai_assistant', trafficType: 'AI Agent', operator: 'Mistral' },
    },
    // Search Crawlers (Applebot/ avoids matching Applebot-Extended)
    {
        pattern: 'Applebot/',
        definition: { name: 'Applebot', category: 'ai_search', trafficType: 'AI Agent', operator: 'Apple' },
    },
    {
        pattern: 'Googlebot',
        definition: { name: 'Googlebot', category: 'search_crawler', trafficType: 'Bot', operator: 'Google' },
    },
    {
        pattern: 'bingbot',
        definition: { name: 'Bingbot', category: 'search_crawler', trafficType: 'Bot', operator: 'Microsoft' },
    },
    {
        pattern: 'Bingbot',
        definition: { name: 'Bingbot', category: 'search_crawler', trafficType: 'Bot', operator: 'Microsoft' },
    },
    {
        pattern: 'YandexBot',
        definition: { name: 'Yandex', category: 'search_crawler', trafficType: 'Bot', operator: 'Yandex' },
    },
    {
        pattern: 'Baiduspider',
        definition: { name: 'Baidu', category: 'search_crawler', trafficType: 'Bot', operator: 'Baidu' },
    },
    {
        pattern: 'DuckDuckBot',
        definition: { name: 'DuckDuckGo', category: 'search_crawler', trafficType: 'Bot', operator: 'DuckDuckGo' },
    },
    {
        pattern: 'Slurp',
        definition: { name: 'Yahoo', category: 'search_crawler', trafficType: 'Bot', operator: 'Yahoo' },
    },
    // SEO Tools
    {
        pattern: 'AhrefsBot',
        definition: { name: 'Ahrefs', category: 'seo_crawler', trafficType: 'Bot', operator: 'Ahrefs' },
    },
    {
        pattern: 'SemrushBot',
        definition: { name: 'Semrush', category: 'seo_crawler', trafficType: 'Bot', operator: 'Semrush' },
    },
    {
        pattern: 'MJ12bot',
        definition: { name: 'Majestic', category: 'seo_crawler', trafficType: 'Bot', operator: 'Majestic' },
    },
    { pattern: 'DotBot', definition: { name: 'Moz', category: 'seo_crawler', trafficType: 'Bot', operator: 'Moz' } },
    // Social Crawlers
    {
        pattern: 'FacebookBot',
        definition: { name: 'Facebook Bot', category: 'social_crawler', trafficType: 'Bot', operator: 'Meta' },
    },
    {
        pattern: 'facebookexternalhit',
        definition: { name: 'Facebook', category: 'social_crawler', trafficType: 'Bot', operator: 'Meta' },
    },
    {
        pattern: 'Twitterbot',
        definition: { name: 'Twitter', category: 'social_crawler', trafficType: 'Bot', operator: 'X' },
    },
    {
        pattern: 'LinkedInBot',
        definition: { name: 'LinkedIn', category: 'social_crawler', trafficType: 'Bot', operator: 'LinkedIn' },
    },
    {
        pattern: 'Pinterest',
        definition: { name: 'Pinterest', category: 'social_crawler', trafficType: 'Bot', operator: 'Pinterest' },
    },
    {
        pattern: 'Slackbot',
        definition: { name: 'Slack', category: 'social_crawler', trafficType: 'Bot', operator: 'Salesforce' },
    },
    {
        pattern: 'TelegramBot',
        definition: { name: 'Telegram', category: 'social_crawler', trafficType: 'Bot', operator: 'Telegram' },
    },
    {
        pattern: 'WhatsApp',
        definition: { name: 'WhatsApp', category: 'social_crawler', trafficType: 'Bot', operator: 'Meta' },
    },
    // Monitoring
    {
        pattern: 'Pingdom',
        definition: { name: 'Pingdom', category: 'monitoring', trafficType: 'Bot', operator: 'SolarWinds' },
    },
    {
        pattern: 'UptimeRobot',
        definition: { name: 'UptimeRobot', category: 'monitoring', trafficType: 'Bot', operator: 'UptimeRobot' },
    },
    {
        pattern: 'Site24x7',
        definition: { name: 'Site24x7', category: 'monitoring', trafficType: 'Bot', operator: 'Zoho' },
    },
    {
        pattern: 'StatusCake',
        definition: { name: 'StatusCake', category: 'monitoring', trafficType: 'Bot', operator: 'StatusCake' },
    },
    {
        pattern: 'Datadog',
        definition: { name: 'Datadog', category: 'monitoring', trafficType: 'Bot', operator: 'Datadog' },
    },
    // HTTP Clients
    {
        pattern: 'curl/',
        definition: { name: 'curl', category: 'http_client', trafficType: 'Automation', operator: 'curl' },
    },
    {
        pattern: 'Wget',
        definition: { name: 'Wget', category: 'http_client', trafficType: 'Automation', operator: 'GNU' },
    },
    {
        pattern: 'python-requests',
        definition: { name: 'Python Requests', category: 'http_client', trafficType: 'Automation', operator: 'Python' },
    },
    {
        pattern: 'axios',
        definition: { name: 'Axios', category: 'http_client', trafficType: 'Automation', operator: 'axios' },
    },
    {
        pattern: 'node-fetch',
        definition: { name: 'Node Fetch', category: 'http_client', trafficType: 'Automation', operator: 'Node.js' },
    },
    {
        pattern: 'Go-http-client',
        definition: { name: 'Go HTTP', category: 'http_client', trafficType: 'Automation', operator: 'Go' },
    },
    {
        pattern: 'okhttp',
        definition: { name: 'OkHttp', category: 'http_client', trafficType: 'Automation', operator: 'Square' },
    },
    {
        pattern: 'Apache-HttpClient',
        definition: { name: 'Apache HTTP', category: 'http_client', trafficType: 'Automation', operator: 'Apache' },
    },
    {
        pattern: 'libwww-perl',
        definition: { name: 'LWP', category: 'http_client', trafficType: 'Automation', operator: 'Perl' },
    },
    {
        pattern: 'Scrapy',
        definition: { name: 'Scrapy', category: 'http_client', trafficType: 'Automation', operator: 'Scrapy' },
    },
    // Headless Browsers
    {
        pattern: 'HeadlessChrome',
        definition: {
            name: 'Headless Chrome',
            category: 'headless_browser',
            trafficType: 'Automation',
            operator: 'Google',
        },
    },
    {
        pattern: 'PhantomJS',
        definition: {
            name: 'PhantomJS',
            category: 'headless_browser',
            trafficType: 'Automation',
            operator: 'PhantomJS',
        },
    },
    {
        pattern: 'Puppeteer',
        definition: { name: 'Puppeteer', category: 'headless_browser', trafficType: 'Automation', operator: 'Google' },
    },
    {
        pattern: 'Playwright',
        definition: {
            name: 'Playwright',
            category: 'headless_browser',
            trafficType: 'Automation',
            operator: 'Microsoft',
        },
    },
    {
        pattern: 'Selenium',
        definition: { name: 'Selenium', category: 'headless_browser', trafficType: 'Automation', operator: 'Selenium' },
    },
]

export const CATEGORY_LABELS: Record<BotCategory, string> = {
    ai_crawler: 'AI crawler',
    ai_search: 'AI search',
    ai_assistant: 'AI assistant',
    search_crawler: 'Search crawler',
    seo_crawler: 'SEO crawler',
    social_crawler: 'Social crawler',
    monitoring: 'Monitoring',
    http_client: 'HTTP client',
    headless_browser: 'Headless browser',
    no_user_agent: 'No user agent',
    regular: 'Regular',
}

export const detectBot = (userAgent: string | null | undefined): BotDefinition | null => {
    if (userAgent == null || userAgent === '') {
        return null
    }
    for (const { pattern, definition } of BOT_DEFINITIONS) {
        if (userAgent.includes(pattern)) {
            return definition
        }
    }
    return null
}

export const getBotName = (userAgent: string | null | undefined): string => {
    return detectBot(userAgent)?.name ?? ''
}

export const isBot = (userAgent: string | null | undefined): boolean => {
    return detectBot(userAgent) !== null
}

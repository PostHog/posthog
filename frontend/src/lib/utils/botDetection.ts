/**
 * Client-side bot detection — mirrors `posthog.hogql_queries.web_analytics.bot_definitions`
 * and the `getBotName` / `isLikelyBot` / `getTrafficCategory`
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
    // Self-declared crawlers observed in production `$http_log` traffic
    // AI crawlers
    {
        pattern: 'VioscaleAIBot',
        definition: { name: 'Vioscale AI', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Vioscale' },
    },
    {
        pattern: 'Amzn-SearchBot',
        definition: { name: 'Amazon Search', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Amazon' },
    },
    {
        pattern: 'LeapwaveVIP',
        definition: { name: 'Leapwave', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Leapwave' },
    },
    {
        pattern: 'docs-puller',
        definition: { name: 'docs-puller', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'docs-puller' },
    },
    {
        pattern: 'ToolchestBot',
        definition: { name: 'Toolchest', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'Toolchest AI' },
    },
    {
        pattern: 'scopy-docs-crawler',
        definition: { name: 'scopy docs crawler', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'scopy' },
    },
    {
        pattern: 'llms-txt-sync',
        definition: {
            name: 'llms-txt-sync',
            category: 'ai_crawler',
            trafficType: 'AI Agent',
            operator: 'llms-txt-sync',
        },
    },
    {
        pattern: 'PromptingBot',
        definition: { name: 'PromptingBot', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'PromptingBot' },
    },
    {
        pattern: 'llm-code-docs-scraper',
        definition: {
            name: 'LLM code docs scraper',
            category: 'ai_crawler',
            trafficType: 'AI Agent',
            operator: 'llm-code-docs-scraper',
        },
    },
    {
        pattern: 'whichapi-bot',
        definition: { name: 'WhichAPI', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'WhichAPI' },
    },
    {
        pattern: 'Codex-YCB2B',
        definition: {
            name: 'Codex public research',
            category: 'ai_crawler',
            trafficType: 'AI Agent',
            operator: 'OpenAI',
        },
    },
    {
        pattern: 'PostHog-BusinessKnowledge',
        definition: {
            name: 'PostHog BusinessKnowledge',
            category: 'ai_crawler',
            trafficType: 'AI Agent',
            operator: 'PostHog',
        },
    },
    {
        pattern: 'LlmsTxtBot',
        definition: { name: 'LlmsTxtBot', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'llms-txt' },
    },
    {
        pattern: 'every-api/',
        definition: { name: 'Every API', category: 'ai_crawler', trafficType: 'AI Agent', operator: 'every-api' },
    },
    {
        pattern: 'RightAIChoiceBot',
        definition: {
            name: 'Right AI Choice',
            category: 'ai_crawler',
            trafficType: 'AI Agent',
            operator: 'Right AI Choice',
        },
    },
    // Search / index crawlers
    {
        pattern: 'redCactiBot',
        definition: { name: 'redCactiBot', category: 'search_crawler', trafficType: 'Bot', operator: 'redCacti' },
    },
    {
        pattern: 'BelleaireCrawler',
        definition: { name: 'BelleaireCrawler', category: 'search_crawler', trafficType: 'Bot', operator: 'Belleaire' },
    },
    {
        pattern: 'PersimmonDesignResearch',
        definition: {
            name: 'Persimmon Design Research',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'Persimmon Software',
        },
    },
    {
        pattern: 'barkReleasesBot',
        definition: { name: 'barkReleasesBot', category: 'search_crawler', trafficType: 'Bot', operator: 'bark' },
    },
    {
        pattern: 'prospector/',
        definition: { name: 'Prospector', category: 'search_crawler', trafficType: 'Bot', operator: 'Rebase' },
    },
    {
        pattern: 'YandexRenderResourcesBot',
        definition: {
            name: 'Yandex Render Resources',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'Yandex',
        },
    },
    {
        pattern: 'YandexAccessibilityBot',
        definition: {
            name: 'Yandex Accessibility',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'Yandex',
        },
    },
    {
        pattern: 'rewebbot',
        definition: { name: 'rewebbot', category: 'search_crawler', trafficType: 'Bot', operator: 'reweb' },
    },
    {
        pattern: 'Querit-SearchBot',
        definition: { name: 'Querit Search', category: 'search_crawler', trafficType: 'Bot', operator: 'Querit' },
    },
    {
        pattern: 'ImpactVibeDesignResearch',
        definition: {
            name: 'ImpactVibe Design Research',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'ImpactVibe',
        },
    },
    {
        pattern: 'crawl-engine',
        definition: { name: 'crawl-engine', category: 'search_crawler', trafficType: 'Bot', operator: 'Creasource' },
    },
    {
        pattern: 'CompanyFeedServer',
        definition: {
            name: 'CompanyFeedServer',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'company-feed-server',
        },
    },
    {
        pattern: 'BranchenbuchBot',
        definition: {
            name: 'BranchenbuchBot',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'Branchenbuch',
        },
    },
    {
        pattern: 'ReachBot',
        definition: { name: 'ReachBot', category: 'search_crawler', trafficType: 'Bot', operator: 'ReachBot' },
    },
    {
        pattern: 'IbouBot',
        definition: { name: 'IbouBot', category: 'search_crawler', trafficType: 'Bot', operator: 'IbouBot' },
    },
    {
        pattern: 'Hypeline',
        definition: { name: 'Hypeline', category: 'search_crawler', trafficType: 'Bot', operator: 'Hypeline' },
    },
    {
        pattern: 'OldSchoolBot',
        definition: { name: 'OldSchoolBot', category: 'search_crawler', trafficType: 'Bot', operator: 'OldSchoolBot' },
    },
    {
        pattern: 'TutusooBot',
        definition: { name: 'TutusooBot', category: 'search_crawler', trafficType: 'Bot', operator: 'Tutusoo' },
    },
    {
        pattern: 'HiringRadarBot',
        definition: { name: 'HiringRadar', category: 'search_crawler', trafficType: 'Bot', operator: 'HiringRadar' },
    },
    {
        pattern: 'slopsearch-linux-crawler',
        definition: { name: 'slopsearch', category: 'search_crawler', trafficType: 'Bot', operator: 'slopsearch' },
    },
    {
        pattern: 'ForgeYourPathAiJobCrawler',
        definition: {
            name: 'ForgeYourPath Job Crawler',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'ForgeYourPath',
        },
    },
    {
        pattern: 'OkaraBot',
        definition: { name: 'OkaraBot', category: 'search_crawler', trafficType: 'Bot', operator: 'OkaraBot' },
    },
    {
        pattern: 'DesignMD-Extract-Bot',
        definition: { name: 'DesignMD Extract', category: 'search_crawler', trafficType: 'Bot', operator: 'DesignMD' },
    },
    {
        pattern: 'LyonlBot',
        definition: { name: 'LyonlBot', category: 'search_crawler', trafficType: 'Bot', operator: 'LyonlBot' },
    },
    {
        pattern: 'Sokjan Crawler',
        definition: { name: 'Sokjan Crawler', category: 'search_crawler', trafficType: 'Bot', operator: 'Sokjan' },
    },
    {
        pattern: 'ScryBot',
        definition: { name: 'ScryBot', category: 'search_crawler', trafficType: 'Bot', operator: 'ScryBot' },
    },
    {
        pattern: 'Heexybot',
        definition: { name: 'Heexybot', category: 'search_crawler', trafficType: 'Bot', operator: 'Heexy' },
    },
    {
        pattern: 'bne.es_bot',
        definition: {
            name: 'Biblioteca Nacional de España',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'Biblioteca Nacional de España',
        },
    },
    {
        pattern: 'Zetlyn',
        definition: { name: 'Zetlyn', category: 'search_crawler', trafficType: 'Bot', operator: 'Zetlyn' },
    },
    {
        pattern: 'algorand-platform-newspaper',
        definition: {
            name: 'Algorand platform newspaper',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'algorand.pxke.me',
        },
    },
    {
        pattern: 'VendiditBot',
        definition: { name: 'Vendidit', category: 'search_crawler', trafficType: 'Bot', operator: 'Vendidit' },
    },
    {
        pattern: 'Zee Company Intelligence',
        definition: {
            name: 'Zee Company Intelligence',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'Lazyweb',
        },
    },
    {
        pattern: 'NicheStuffBot',
        definition: { name: 'NicheStuff', category: 'search_crawler', trafficType: 'Bot', operator: 'NicheStuff' },
    },
    {
        pattern: 'Axiom-DocBot',
        definition: { name: 'Axiom DocBot', category: 'search_crawler', trafficType: 'Bot', operator: 'Axiom' },
    },
    {
        pattern: 'RealPressBot',
        definition: { name: 'RealPressBot', category: 'search_crawler', trafficType: 'Bot', operator: 'real.press' },
    },
    {
        pattern: 'StraddleLibraryBot',
        definition: { name: 'Straddle Library', category: 'search_crawler', trafficType: 'Bot', operator: 'Straddle' },
    },
    {
        pattern: 'LurantaBot',
        definition: { name: 'Luranta', category: 'search_crawler', trafficType: 'Bot', operator: 'Luranta' },
    },
    {
        pattern: 'UnstenciledBot',
        definition: { name: 'Unstenciled', category: 'search_crawler', trafficType: 'Bot', operator: 'Unstenciled' },
    },
    {
        pattern: 'InloraBot',
        definition: { name: 'Inlora', category: 'search_crawler', trafficType: 'Bot', operator: 'Inlora' },
    },
    {
        pattern: 'EfficientRustCrawler',
        definition: {
            name: 'Efficient Rust Crawler',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'Xape',
        },
    },
    {
        pattern: 'DatalenkCreatorResearch',
        definition: {
            name: 'Datalenk Creator Research',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'Datalenk',
        },
    },
    {
        pattern: 'Wrzutka-Bot',
        definition: { name: 'Wrzutka', category: 'search_crawler', trafficType: 'Bot', operator: 'Wrzutka' },
    },
    {
        pattern: 'Polon/',
        definition: { name: 'Polon', category: 'search_crawler', trafficType: 'Bot', operator: 'Polon' },
    },
    {
        pattern: 'Babel42Bot',
        definition: { name: 'Babel42', category: 'search_crawler', trafficType: 'Bot', operator: 'Babel42' },
    },
    {
        pattern: 'jscrawler',
        definition: { name: 'jscrawler', category: 'search_crawler', trafficType: 'Bot', operator: 'jscrawler' },
    },
    {
        pattern: 'PolycoreSupabaseDetector',
        definition: {
            name: 'Polycore Supabase Detector',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'Polycore',
        },
    },
    {
        pattern: 'UnboundCompute-PublicSnapshot',
        definition: {
            name: 'UnboundCompute Public Snapshot',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'UnboundCompute',
        },
    },
    {
        pattern: 'swissAItalentBot',
        definition: {
            name: 'swissAItalentBot',
            category: 'search_crawler',
            trafficType: 'Bot',
            operator: 'swissaitalent.ch',
        },
    },
    // SEO / marketing crawlers
    {
        pattern: 'LaunchReadyCodeBot',
        definition: {
            name: 'LaunchReadyCodeBot',
            category: 'seo_crawler',
            trafficType: 'Bot',
            operator: 'LaunchReadyCode',
        },
    },
    {
        pattern: 'PricingArchiveBot',
        definition: {
            name: 'PricingArchiveBot',
            category: 'seo_crawler',
            trafficType: 'Bot',
            operator: 'pricing-archive',
        },
    },
    {
        pattern: 'SEOMasterBot',
        definition: { name: 'SEOMasterBot', category: 'seo_crawler', trafficType: 'Bot', operator: 'SEOMaster' },
    },
    {
        pattern: 'CanICancelIt-LinkCheck',
        definition: {
            name: 'CanICancelIt LinkCheck',
            category: 'seo_crawler',
            trafficType: 'Bot',
            operator: 'CanICancelIt',
        },
    },
    {
        pattern: 'serpstatbot',
        definition: { name: 'Serpstat', category: 'seo_crawler', trafficType: 'Bot', operator: 'Serpstat' },
    },
    {
        pattern: 'StackPick',
        definition: { name: 'StackPick', category: 'seo_crawler', trafficType: 'Bot', operator: 'StackPick' },
    },
    {
        pattern: 'UXXRAYBot',
        definition: { name: 'UXXRAY', category: 'seo_crawler', trafficType: 'Bot', operator: 'UXXRAY' },
    },
    {
        pattern: 'NoFluffGraderBot',
        definition: {
            name: 'NoFluff Grader',
            category: 'seo_crawler',
            trafficType: 'Bot',
            operator: 'NoFluff Marketing',
        },
    },
    {
        pattern: 'PagePilot-SiteAudit',
        definition: {
            name: 'PagePilot Site Audit',
            category: 'seo_crawler',
            trafficType: 'Bot',
            operator: 'PagePilot',
        },
    },
    {
        pattern: 'double-ats-customer-discoverer',
        definition: {
            name: 'Double ATS Customer Discoverer',
            category: 'seo_crawler',
            trafficType: 'Bot',
            operator: 'Double',
        },
    },
    {
        pattern: 'BenchRankBot',
        definition: { name: 'BenchRank', category: 'seo_crawler', trafficType: 'Bot', operator: 'BenchRank' },
    },
    // Social / link-preview crawlers
    {
        pattern: 'PagePeeker',
        definition: { name: 'PagePeeker', category: 'social_crawler', trafficType: 'Bot', operator: 'PagePeeker' },
    },
    {
        pattern: 'Synapse (bot',
        definition: { name: 'Synapse', category: 'social_crawler', trafficType: 'Bot', operator: 'Matrix.org' },
    },
    {
        pattern: 'Unfurlist',
        definition: { name: 'Unfurlist', category: 'social_crawler', trafficType: 'Bot', operator: 'Doist' },
    },
    // Uptime / monitors / probes
    {
        pattern: 'heap.page source monitor',
        definition: { name: 'heap.page', category: 'monitoring', trafficType: 'Bot', operator: 'heap.page' },
    },
    {
        pattern: 'PulseWatch-Prober',
        definition: { name: 'PulseWatch', category: 'monitoring', trafficType: 'Bot', operator: 'PulseWatch' },
    },
    {
        pattern: 'Scryer/',
        definition: { name: 'Scryer', category: 'monitoring', trafficType: 'Bot', operator: 'Scryer' },
    },
    {
        pattern: 'UnusualAgentAudit',
        definition: { name: 'UnusualAgentAudit', category: 'monitoring', trafficType: 'Bot', operator: 'unusual.ai' },
    },
    {
        pattern: 'VersionWatchBot',
        definition: { name: 'VersionWatch', category: 'monitoring', trafficType: 'Bot', operator: 'VersionWatch' },
    },
    {
        pattern: 'a14y/',
        definition: { name: 'a14y', category: 'monitoring', trafficType: 'Bot', operator: 'a14y' },
    },
    {
        pattern: 'UptimeLensBot',
        definition: { name: 'UptimeLens', category: 'monitoring', trafficType: 'Bot', operator: 'UptimeLens' },
    },
    {
        pattern: 'InterruptIndexBot',
        definition: { name: 'InterruptIndex', category: 'monitoring', trafficType: 'Bot', operator: 'InterruptIndex' },
    },
    {
        pattern: 'CurbCutScanner',
        definition: { name: 'CurbCut Scanner', category: 'monitoring', trafficType: 'Bot', operator: 'CurbCut' },
    },
    {
        pattern: 'VantageBot',
        definition: { name: 'VantageBot', category: 'monitoring', trafficType: 'Bot', operator: 'webapp-monitor' },
    },
    {
        pattern: 'NimbusBlocklistSync',
        definition: { name: 'Nimbus Blocklist Sync', category: 'monitoring', trafficType: 'Bot', operator: 'Nimbus' },
    },
    // HTTP clients
    {
        pattern: 'MrAnandPortfolio',
        definition: { name: 'MrAnandPortfolio', category: 'http_client', trafficType: 'Bot', operator: 'mranand.com' },
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

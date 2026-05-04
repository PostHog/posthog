import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'
import { LemonSelect, Popover } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isWebAnalyticsPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { WebAnalyticsPropertyFilters } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { botAnalyticsLogic } from './botAnalyticsLogic'
import { BOT_ANALYTICS_EVENTS } from './common'

interface BotDef {
    name: string
    category: string
}

// Curated list of known bot user-agents used to populate the helper dropdowns. Authoritative
// data lives in the ingestion-side bot detector — this is just the UI hint list.
const BOT_DEFINITIONS_LIST: BotDef[] = [
    { name: 'Ahrefs', category: 'seo_crawler' },
    { name: 'Ahrefs Site Audit', category: 'seo_crawler' },
    { name: 'Amazon', category: 'ai_crawler' },
    { name: 'Anthropic', category: 'ai_crawler' },
    { name: 'Apache HTTP', category: 'http_client' },
    { name: 'Apple AI', category: 'ai_search' },
    { name: 'Applebot', category: 'ai_search' },
    { name: 'Axios', category: 'http_client' },
    { name: 'Baidu', category: 'search_crawler' },
    { name: 'Barkrowler', category: 'seo_crawler' },
    { name: 'Bingbot', category: 'search_crawler' },
    { name: 'Brightbot', category: 'ai_crawler' },
    { name: 'ByteDance', category: 'ai_crawler' },
    { name: 'ChatGPT', category: 'ai_assistant' },
    { name: 'Chrome Prefetch Proxy', category: 'http_client' },
    { name: 'Claude', category: 'ai_crawler' },
    { name: 'Claude Search', category: 'ai_search' },
    { name: 'Claude User', category: 'ai_assistant' },
    { name: 'Claude Web', category: 'ai_crawler' },
    { name: 'Cohere', category: 'ai_crawler' },
    { name: 'Common Crawl', category: 'ai_crawler' },
    { name: 'curl', category: 'http_client' },
    { name: 'Datadog', category: 'monitoring' },
    { name: 'Diffbot', category: 'ai_crawler' },
    { name: 'DuckDuckGo', category: 'search_crawler' },
    { name: 'DuckDuckGo AI', category: 'ai_assistant' },
    { name: 'Facebook', category: 'social_crawler' },
    { name: 'Facebook Bot', category: 'social_crawler' },
    { name: 'Go HTTP', category: 'http_client' },
    { name: 'Google AI', category: 'ai_crawler' },
    { name: 'Google Ads', category: 'search_crawler' },
    { name: 'Google Cloud Vertex', category: 'ai_crawler' },
    { name: 'Google Inspection', category: 'search_crawler' },
    { name: 'GoogleOther', category: 'ai_crawler' },
    { name: 'Googlebot', category: 'search_crawler' },
    { name: 'GPTBot', category: 'ai_crawler' },
    { name: 'Headless Chrome', category: 'headless_browser' },
    { name: 'LinkedIn', category: 'social_crawler' },
    { name: 'LWP', category: 'http_client' },
    { name: 'Majestic', category: 'seo_crawler' },
    { name: 'Meta AI', category: 'ai_crawler' },
    { name: 'Meta Fetcher', category: 'ai_assistant' },
    { name: 'Mistral AI', category: 'ai_assistant' },
    { name: 'Moz', category: 'seo_crawler' },
    { name: 'Mozlila Typo Bot', category: 'headless_browser' },
    { name: 'Node Fetch', category: 'http_client' },
    { name: 'OkHttp', category: 'http_client' },
    { name: 'OpenAI Search', category: 'ai_search' },
    { name: 'Perplexity', category: 'ai_search' },
    { name: 'Perplexity User', category: 'ai_assistant' },
    { name: 'Petal', category: 'ai_crawler' },
    { name: 'PhantomJS', category: 'headless_browser' },
    { name: 'Pingdom', category: 'monitoring' },
    { name: 'Pinterest', category: 'social_crawler' },
    { name: 'Playwright', category: 'headless_browser' },
    { name: 'Puppeteer', category: 'headless_browser' },
    { name: 'Python Requests', category: 'http_client' },
    { name: 'Scrapy', category: 'http_client' },
    { name: 'Selenium', category: 'headless_browser' },
    { name: 'Semrush', category: 'seo_crawler' },
    { name: 'Site24x7', category: 'monitoring' },
    { name: 'Slack', category: 'social_crawler' },
    { name: 'StatusCake', category: 'monitoring' },
    { name: 'Telegram', category: 'social_crawler' },
    { name: 'TikTok AI', category: 'ai_crawler' },
    { name: 'Timpi', category: 'ai_crawler' },
    { name: 'Twitter', category: 'social_crawler' },
    { name: 'UptimeRobot', category: 'monitoring' },
    { name: 'Webz.io', category: 'ai_crawler' },
    { name: 'Webz.io Extended', category: 'ai_crawler' },
    { name: 'Wget', category: 'http_client' },
    { name: 'WhatsApp', category: 'social_crawler' },
    { name: 'Yahoo', category: 'search_crawler' },
    { name: 'Yandex', category: 'search_crawler' },
]

const CATEGORY_LABELS: Record<string, string> = {
    ai_crawler: 'AI crawler',
    ai_search: 'AI search',
    ai_assistant: 'AI assistant',
    search_crawler: 'Search crawler',
    seo_crawler: 'SEO crawler',
    social_crawler: 'Social crawler',
    monitoring: 'Monitoring',
    http_client: 'HTTP client',
    headless_browser: 'Headless browser',
}

function getFilteredBotOptions(
    selectedCategory: string | null,
    selectedCrawler: string | null
): {
    categories: { label: string; value: string | null }[]
    crawlers: { label: string; value: string | null }[]
} {
    let filtered = BOT_DEFINITIONS_LIST

    if (selectedCategory) {
        filtered = filtered.filter((b) => b.category === selectedCategory)
    }
    if (selectedCrawler) {
        filtered = filtered.filter((b) => b.name === selectedCrawler)
    }

    const categoryValues = [...new Set(filtered.map((b) => b.category))].sort()
    const crawlerValues = [...new Set(filtered.map((b) => b.name))].sort()

    return {
        categories: [
            { label: 'All categories', value: null },
            ...categoryValues.map((c) => ({ label: CATEGORY_LABELS[c] || c, value: c })),
        ],
        crawlers: [{ label: 'All crawlers', value: null }, ...crawlerValues.map((n) => ({ label: n, value: n }))],
    }
}

function getBotFilterValue(filters: WebAnalyticsPropertyFilters, key: string): string | null {
    const filter = filters.find((f) => 'key' in f && f.key === key)
    return filter && 'value' in filter ? ((filter.value as string[])?.[0] ?? null) : null
}

const BotHelperSelect = ({
    propertyKey,
    placeholder,
    options,
}: {
    propertyKey: string
    placeholder: string
    options: { label: string; value: string | null }[]
}): JSX.Element => {
    const { rawBotAnalyticsFilters } = useValues(botAnalyticsLogic)
    const { setBotAnalyticsFilters } = useActions(botAnalyticsLogic)

    const currentValue = getBotFilterValue(rawBotAnalyticsFilters, propertyKey)

    const onChange = (value: string | null): void => {
        const otherFilters = rawBotAnalyticsFilters.filter((f) => !('key' in f && f.key === propertyKey))
        if (value) {
            setBotAnalyticsFilters([
                ...otherFilters,
                {
                    key: propertyKey,
                    value: [value],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ])
        } else {
            setBotAnalyticsFilters(otherFilters)
        }
    }

    return (
        <LemonSelect
            size="small"
            value={currentValue}
            onChange={onChange}
            options={options}
            placeholder={placeholder}
            dropdownMatchSelectWidth={false}
            fullWidth
        />
    )
}

// Bot analytics scopes filtering to event properties — `$virt_*` virtual properties
// (bot name, traffic category, is_bot) live there and are the meaningful filter surface.
const BOT_TAXONOMIC_GROUP_TYPES = [TaxonomicFilterGroupType.EventProperties]

export const BotPropertyFilters = (): JSX.Element => {
    const [displayFilters, setDisplayFilters] = useState(false)
    const { rawBotAnalyticsFilters } = useValues(botAnalyticsLogic)
    const { setBotAnalyticsFilters } = useActions(botAnalyticsLogic)

    const selectedCategory = getBotFilterValue(rawBotAnalyticsFilters, '$virt_traffic_category')
    const selectedCrawler = getBotFilterValue(rawBotAnalyticsFilters, '$virt_bot_name')
    const { categories, crawlers } = getFilteredBotOptions(selectedCategory, selectedCrawler)

    const activeFilterCount = rawBotAnalyticsFilters.length

    const filtersContent = (
        <div className="p-3 w-96 max-w-[90vw]">
            <div className="space-y-4">
                <div>
                    <div className="text-xs font-semibold text-muted uppercase mb-2">Crawler</div>
                    <BotHelperSelect propertyKey="$virt_bot_name" placeholder="All crawlers" options={crawlers} />
                </div>
                <div>
                    <div className="text-xs font-semibold text-muted uppercase mb-2">Category</div>
                    <BotHelperSelect
                        propertyKey="$virt_traffic_category"
                        placeholder="All categories"
                        options={categories}
                    />
                </div>
                <LemonDivider />
                <div>
                    <div className="text-xs font-semibold text-muted uppercase mb-2">Property filters</div>
                    <PropertyFilters
                        disablePopover
                        taxonomicGroupTypes={BOT_TAXONOMIC_GROUP_TYPES}
                        onChange={(filters) => setBotAnalyticsFilters(filters.filter(isWebAnalyticsPropertyFilter))}
                        propertyFilters={rawBotAnalyticsFilters}
                        pageKey="bot-analytics"
                        eventNames={BOT_ANALYTICS_EVENTS}
                    />
                </div>
            </div>
        </div>
    )

    return (
        <Popover
            visible={displayFilters}
            onClickOutside={() => setDisplayFilters(false)}
            placement="bottom-start"
            overlay={filtersContent}
        >
            <LemonButton
                icon={
                    <IconWithCount count={activeFilterCount} showZero={false}>
                        <IconFilter />
                    </IconWithCount>
                }
                type="secondary"
                size="small"
                data-attr="bot-analytics-filters"
                onClick={() => setDisplayFilters(!displayFilters)}
            >
                Filters
            </LemonButton>
        </Popover>
    )
}

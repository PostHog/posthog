import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import { IconFilter, IconGlobe, IconPhone, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonInput, LemonSelect, Popover, Tooltip } from '@posthog/lemon-ui'

import { baseModifier } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { AuthorizedUrlListType, authorizedUrlListLogic } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { LiveUserCount } from 'lib/components/LiveUserCount'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import {
    convertPropertyGroupToProperties,
    isEventPersonOrSessionPropertyFilter,
    isWebAnalyticsPropertyFilter,
} from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconLink, IconMonitor, IconWithCount } from 'lib/lemon-ui/icons/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import MaxTool from 'scenes/max/MaxTool'
import { Scene } from 'scenes/sceneTypes'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { WebAnalyticsPropertyFilters } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyMathType, PropertyOperator } from '~/types'

import { BotTrafficFilter, ProductTab, faviconUrl } from './common'
import { webAnalyticsDateMapping } from './constants'
import { PathCleaningToggle } from './PathCleaningToggle'
import { TableSortingIndicator } from './TableSortingIndicator'
import { FilterPresetsDropdown } from './WebAnalyticsFilterPresets'
import { webAnalyticsFilterPresetsLogic } from './webAnalyticsFilterPresetsLogic'
import { WebAnalyticsFiltersV2MigrationBanner } from './WebAnalyticsFiltersV2MigrationBanner'
import { webAnalyticsLogic } from './webAnalyticsLogic'
import { WebConversionGoal } from './WebConversionGoal'
import {
    WEB_ANALYTICS_PROPERTY_ALLOW_LIST,
    WebPropertyFilters,
    getWebAnalyticsTaxonomicGroupTypes,
} from './WebPropertyFilters'

const BotTrafficToggle = (): JSX.Element | null => {
    const { botTrafficFilter, productTab } = useValues(webAnalyticsLogic)
    const { setBotTrafficFilter } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_BOT_ANALYSIS] || productTab === ProductTab.BOT_ANALYTICS) {
        return null
    }

    return (
        <LemonSegmentedSelect
            value={botTrafficFilter}
            onChange={(value) => setBotTrafficFilter(value as BotTrafficFilter)}
            options={[
                { value: 'regular', label: 'Regular' },
                { value: 'bot', label: 'Bot' },
                { value: 'all', label: 'All' },
            ]}
            size="small"
        />
    )
}

interface BotDef {
    name: string
    operator: string
    category: string
}

const BOT_DEFINITIONS_LIST: BotDef[] = [
    { name: 'Ahrefs', operator: 'Ahrefs', category: 'seo_crawler' },
    { name: 'Ahrefs Site Audit', operator: 'Ahrefs', category: 'seo_crawler' },
    { name: 'Amazon', operator: 'Amazon', category: 'ai_crawler' },
    { name: 'Anthropic', operator: 'Anthropic', category: 'ai_crawler' },
    { name: 'Apache HTTP', operator: 'Apache', category: 'http_client' },
    { name: 'Apple AI', operator: 'Apple', category: 'ai_search' },
    { name: 'Applebot', operator: 'Apple', category: 'ai_search' },
    { name: 'Axios', operator: 'axios', category: 'http_client' },
    { name: 'Baidu', operator: 'Baidu', category: 'search_crawler' },
    { name: 'Barkrowler', operator: 'Babbar', category: 'seo_crawler' },
    { name: 'Bingbot', operator: 'Microsoft', category: 'search_crawler' },
    { name: 'Brightbot', operator: 'Bright Data', category: 'ai_crawler' },
    { name: 'ByteDance', operator: 'ByteDance', category: 'ai_crawler' },
    { name: 'ChatGPT', operator: 'OpenAI', category: 'ai_assistant' },
    { name: 'Chrome Prefetch Proxy', operator: 'Google', category: 'http_client' },
    { name: 'Claude', operator: 'Anthropic', category: 'ai_crawler' },
    { name: 'Claude Search', operator: 'Anthropic', category: 'ai_search' },
    { name: 'Claude User', operator: 'Anthropic', category: 'ai_assistant' },
    { name: 'Claude Web', operator: 'Anthropic', category: 'ai_crawler' },
    { name: 'Cohere', operator: 'Cohere', category: 'ai_crawler' },
    { name: 'Common Crawl', operator: 'Common Crawl', category: 'ai_crawler' },
    { name: 'curl', operator: 'curl', category: 'http_client' },
    { name: 'Datadog', operator: 'Datadog', category: 'monitoring' },
    { name: 'Diffbot', operator: 'Diffbot', category: 'ai_crawler' },
    { name: 'DuckDuckGo', operator: 'DuckDuckGo', category: 'search_crawler' },
    { name: 'DuckDuckGo AI', operator: 'DuckDuckGo', category: 'ai_assistant' },
    { name: 'Facebook', operator: 'Meta', category: 'social_crawler' },
    { name: 'Facebook Bot', operator: 'Meta', category: 'social_crawler' },
    { name: 'Go HTTP', operator: 'Go', category: 'http_client' },
    { name: 'Google AI', operator: 'Google', category: 'ai_crawler' },
    { name: 'Google Ads', operator: 'Google', category: 'search_crawler' },
    { name: 'Google Cloud Vertex', operator: 'Google', category: 'ai_crawler' },
    { name: 'Google Inspection', operator: 'Google', category: 'search_crawler' },
    { name: 'GoogleOther', operator: 'Google', category: 'ai_crawler' },
    { name: 'Googlebot', operator: 'Google', category: 'search_crawler' },
    { name: 'GPTBot', operator: 'OpenAI', category: 'ai_crawler' },
    { name: 'Headless Chrome', operator: 'Google', category: 'headless_browser' },
    { name: 'LinkedIn', operator: 'LinkedIn', category: 'social_crawler' },
    { name: 'LWP', operator: 'Perl', category: 'http_client' },
    { name: 'Majestic', operator: 'Majestic', category: 'seo_crawler' },
    { name: 'Meta AI', operator: 'Meta', category: 'ai_crawler' },
    { name: 'Meta Fetcher', operator: 'Meta', category: 'ai_assistant' },
    { name: 'Mistral AI', operator: 'Mistral', category: 'ai_assistant' },
    { name: 'Moz', operator: 'Moz', category: 'seo_crawler' },
    { name: 'Mozlila Typo Bot', operator: 'Unknown', category: 'headless_browser' },
    { name: 'Node Fetch', operator: 'Node.js', category: 'http_client' },
    { name: 'OkHttp', operator: 'Square', category: 'http_client' },
    { name: 'OpenAI Search', operator: 'OpenAI', category: 'ai_search' },
    { name: 'Perplexity', operator: 'Perplexity', category: 'ai_search' },
    { name: 'Perplexity User', operator: 'Perplexity', category: 'ai_assistant' },
    { name: 'Petal', operator: 'Huawei', category: 'ai_crawler' },
    { name: 'PhantomJS', operator: 'PhantomJS', category: 'headless_browser' },
    { name: 'Pingdom', operator: 'SolarWinds', category: 'monitoring' },
    { name: 'Pinterest', operator: 'Pinterest', category: 'social_crawler' },
    { name: 'Playwright', operator: 'Microsoft', category: 'headless_browser' },
    { name: 'Puppeteer', operator: 'Google', category: 'headless_browser' },
    { name: 'Python Requests', operator: 'Python', category: 'http_client' },
    { name: 'Scrapy', operator: 'Scrapy', category: 'http_client' },
    { name: 'Selenium', operator: 'Selenium', category: 'headless_browser' },
    { name: 'Semrush', operator: 'Semrush', category: 'seo_crawler' },
    { name: 'Site24x7', operator: 'Zoho', category: 'monitoring' },
    { name: 'Slack', operator: 'Salesforce', category: 'social_crawler' },
    { name: 'StatusCake', operator: 'StatusCake', category: 'monitoring' },
    { name: 'Telegram', operator: 'Telegram', category: 'social_crawler' },
    { name: 'TikTok AI', operator: 'ByteDance', category: 'ai_crawler' },
    { name: 'Timpi', operator: 'Timpi', category: 'ai_crawler' },
    { name: 'Twitter', operator: 'X', category: 'social_crawler' },
    { name: 'UptimeRobot', operator: 'UptimeRobot', category: 'monitoring' },
    { name: 'Webz.io', operator: 'Webz.io', category: 'ai_crawler' },
    { name: 'Webz.io Extended', operator: 'Webz.io', category: 'ai_crawler' },
    { name: 'Wget', operator: 'GNU', category: 'http_client' },
    { name: 'WhatsApp', operator: 'Meta', category: 'social_crawler' },
    { name: 'Yahoo', operator: 'Yahoo', category: 'search_crawler' },
    { name: 'Yandex', operator: 'Yandex', category: 'search_crawler' },
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
    selectedCrawler: string | null,
    selectedOperator: string | null
): {
    categories: { label: string; value: string | null }[]
    crawlers: { label: string; value: string | null }[]
    operators: { label: string; value: string | null }[]
} {
    let filtered = BOT_DEFINITIONS_LIST

    if (selectedCategory) {
        filtered = filtered.filter((b) => b.category === selectedCategory)
    }
    if (selectedCrawler) {
        filtered = filtered.filter((b) => b.name === selectedCrawler)
    }
    if (selectedOperator) {
        filtered = filtered.filter((b) => b.operator === selectedOperator)
    }

    const categoryValues = [...new Set(filtered.map((b) => b.category))].sort()
    const crawlerValues = [...new Set(filtered.map((b) => b.name))].sort()
    const operatorValues = [...new Set(filtered.map((b) => b.operator))].sort()

    return {
        categories: [
            { label: 'All categories', value: null },
            ...categoryValues.map((c) => ({ label: CATEGORY_LABELS[c] || c, value: c })),
        ],
        crawlers: [{ label: 'All crawlers', value: null }, ...crawlerValues.map((n) => ({ label: n, value: n }))],
        operators: [{ label: 'All operators', value: null }, ...operatorValues.map((o) => ({ label: o, value: o }))],
    }
}

function getBotFilterValue(filters: WebAnalyticsPropertyFilters, key: string): string | null {
    const filter = filters.find((f) => 'key' in f && f.key === key)
    return filter && 'value' in filter ? ((filter.value as string[])?.[0] ?? null) : null
}

const BotPropertySelect = ({
    propertyKey,
    placeholder,
    options,
}: {
    propertyKey: string
    placeholder: string
    options: { label: string; value: string | null }[]
}): JSX.Element => {
    const { rawWebAnalyticsFilters } = useValues(webAnalyticsLogic)
    const { setWebAnalyticsFilters } = useActions(webAnalyticsLogic)

    const currentValue = getBotFilterValue(rawWebAnalyticsFilters, propertyKey)

    const onChange = (value: string | null): void => {
        const otherFilters = rawWebAnalyticsFilters.filter((f) => !('key' in f && f.key === propertyKey))
        if (value) {
            setWebAnalyticsFilters([
                ...otherFilters,
                {
                    key: propertyKey,
                    value: [value],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ])
        } else {
            setWebAnalyticsFilters(otherFilters)
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
        />
    )
}

export const BotAnalyticsFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        rawWebAnalyticsFilters,
    } = useValues(webAnalyticsLogic)
    const { setDates } = useActions(webAnalyticsLogic)

    const selectedCategory = getBotFilterValue(rawWebAnalyticsFilters, '$virt_traffic_category')
    const selectedCrawler = getBotFilterValue(rawWebAnalyticsFilters, '$virt_bot_name')
    const selectedOperator = getBotFilterValue(rawWebAnalyticsFilters, '$virt_bot_operator')
    const { categories, crawlers, operators } = getFilteredBotOptions(
        selectedCategory,
        selectedCrawler,
        selectedOperator
    )

    return (
        <FilterBar
            top={tabs}
            left={
                <>
                    <ReloadAll iconOnly />
                    <DateFilter
                        dateOptions={webAnalyticsDateMapping}
                        allowTimePrecision
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={setDates}
                    />
                    <BotPropertySelect
                        propertyKey="$virt_traffic_category"
                        placeholder="All categories"
                        options={categories}
                    />
                    <BotPropertySelect propertyKey="$virt_bot_name" placeholder="All crawlers" options={crawlers} />
                    <BotPropertySelect
                        propertyKey="$virt_bot_operator"
                        placeholder="All operators"
                        options={operators}
                    />
                </>
            }
        />
    )
}

const CondensedWebAnalyticsFilterBar = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        isPathCleaningEnabled,
    } = useValues(webAnalyticsLogic)
    const { setDates, setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <>
            <WebAnalyticsFiltersV2MigrationBanner />
            <IncompatibleFiltersWarning />
            <FilterBar
                top={tabs}
                left={
                    <>
                        <ReloadAll iconOnly />
                        <DateFilter
                            dateOptions={webAnalyticsDateMapping}
                            allowTimePrecision
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            onChange={setDates}
                        />
                        <WebAnalyticsCompareFilter />
                    </>
                }
                right={
                    <>
                        <BotTrafficToggle />
                        <ShareButton />
                        <WebVitalsPercentileToggle />
                        {featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2] && <FilterPresetsDropdown />}
                        <FiltersPopover />
                        <PathCleaningToggle value={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />
                        <WebAnalyticsDomainSelector />
                        <TableSortingIndicator />
                    </>
                }
            />
        </>
    )
}

export const WebAnalyticsFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        isPathCleaningEnabled,
    } = useValues(webAnalyticsLogic)
    const { setDates, setIsPathCleaningEnabled } = useActions(webAnalyticsLogic)

    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2] || featureFlags[FEATURE_FLAGS.CONDENSED_FILTER_BAR]) {
        return <CondensedWebAnalyticsFilterBar tabs={tabs} />
    }

    return (
        <>
            <IncompatibleFiltersWarning />

            <div data-attr="web-analytics-filters">
                <FilterBar
                    top={tabs}
                    left={
                        <>
                            <ReloadAll iconOnly />
                            <DateFilter
                                dateOptions={webAnalyticsDateMapping}
                                allowTimePrecision
                                dateFrom={dateFrom}
                                dateTo={dateTo}
                                onChange={setDates}
                            />

                            <WebAnalyticsDomainSelector />
                            <WebAnalyticsDeviceToggle />
                            <LiveUserCount
                                docLink="https://posthog.com/docs/web-analytics/faq#i-am-online-but-the-online-user-count-is-not-reflecting-my-user"
                                dataAttr="web-analytics-live-user-count"
                            />
                        </>
                    }
                    right={
                        <>
                            <BotTrafficToggle />
                            <WebAnalyticsCompareFilter />

                            <WebConversionGoal />
                            <TableSortingIndicator />

                            <WebVitalsPercentileToggle />
                            <PathCleaningToggle value={isPathCleaningEnabled} onChange={setIsPathCleaningEnabled} />

                            <WebAnalyticsAIFilters>
                                <WebPropertyFilters />
                            </WebAnalyticsAIFilters>
                        </>
                    }
                />
            </div>
        </>
    )
}

const WebAnalyticsAIFilters = ({ children }: { children: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        rawWebAnalyticsFilters,
        isPathCleaningEnabled,
        compareFilter,
    } = useValues(webAnalyticsLogic)
    const { setDates, setWebAnalyticsFilters, setIsPathCleaningEnabled, setCompareFilter } =
        useActions(webAnalyticsLogic)

    return (
        <MaxTool
            identifier="filter_web_analytics"
            context={{
                current_filters: {
                    date_from: dateFrom,
                    date_to: dateTo,
                    properties: rawWebAnalyticsFilters,
                    doPathCleaning: isPathCleaningEnabled,
                    compareFilter: compareFilter,
                },
            }}
            contextDescription={{
                text: 'Current filters',
                icon: <IconFilter />,
            }}
            callback={(toolOutput: Record<string, any>) => {
                if (toolOutput.properties !== undefined) {
                    const flattenedProperties = convertPropertyGroupToProperties(toolOutput.properties)
                    setWebAnalyticsFilters(flattenedProperties?.filter(isEventPersonOrSessionPropertyFilter) ?? [])
                }
                if (toolOutput.date_from !== undefined && toolOutput.date_to !== undefined) {
                    setDates(toolOutput.date_from, toolOutput.date_to)
                }
                if (toolOutput.doPathCleaning !== undefined) {
                    setIsPathCleaningEnabled(toolOutput.doPathCleaning)
                }
                if (toolOutput.compareFilter !== undefined) {
                    setCompareFilter(toolOutput.compareFilter)
                }
            }}
            initialMaxPrompt="Filter web analytics data for "
            suggestions={[
                'Show mobile traffic from last 30 days for the US',
                'Filter only sessions greater than 2 minutes coming from organic search',
                "Don't include direct traffic and show data for the last 7 days",
            ]}
        >
            {children}
        </MaxTool>
    )
}

export const WebAnalyticsDomainSelector = (): JSX.Element => {
    const { validatedDomainFilter, hasHostFilter, authorizedDomains, showProposedURLForm } =
        useValues(webAnalyticsLogic)
    const { setDomainFilter } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <LemonSelect
            className="grow md:grow-0"
            size="small"
            value={hasHostFilter ? 'host' : (validatedDomainFilter ?? 'all')}
            icon={<IconGlobe />}
            onChange={(value) => setDomainFilter(value)}
            menu={{ closeParentPopoverOnClickInside: !showProposedURLForm }}
            options={[
                {
                    options: [
                        {
                            label: 'All domains',
                            value: 'all',
                        },
                        ...(hasHostFilter
                            ? [
                                  {
                                      label: 'All domains (host filter active)',
                                      value: 'host',
                                  },
                              ]
                            : []),
                        ...authorizedDomains.map((domain) => {
                            let hostname: string | null = null
                            try {
                                hostname = new URL(domain).hostname
                            } catch {
                                // skip favicon for malformed URLs
                            }
                            return {
                                label: domain,
                                value: domain,
                                ...(hostname && featureFlags[FEATURE_FLAGS.SHOW_REFERRER_FAVICON]
                                    ? {
                                          icon: (
                                              <img
                                                  src={faviconUrl(hostname)}
                                                  width={16}
                                                  height={16}
                                                  alt={`${domain} favicon`}
                                                  onError={(e) => (e.currentTarget.style.display = 'none')}
                                              />
                                          ),
                                      }
                                    : {}),
                            }
                        }),
                    ],
                    footer: showProposedURLForm ? <AddAuthorizedUrlForm /> : <AddSuggestedAuthorizedUrlList />,
                },
            ]}
        />
    )
}

const WebAnalyticsDeviceToggle = (): JSX.Element => {
    const { deviceTypeFilter } = useValues(webAnalyticsLogic)
    const { setDeviceTypeFilter } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Device toggle shortcuts (Web Analytics-specific)
    useAppShortcut({
        name: 'WebAnalyticsDesktop',
        keybind: [[...baseModifier, 'p']],
        intent: 'Filter desktop devices',
        interaction: 'function',
        callback: () => setDeviceTypeFilter(deviceTypeFilter === 'Desktop' ? null : 'Desktop'),
        scope: Scene.WebAnalytics,
    })
    useAppShortcut({
        name: 'WebAnalyticsMobile',
        keybind: [[...baseModifier, 'm']],
        intent: 'Filter mobile devices',
        interaction: 'function',
        callback: () => setDeviceTypeFilter(deviceTypeFilter === 'Mobile' ? null : 'Mobile'),
        scope: Scene.WebAnalytics,
    })

    if (featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2] || featureFlags[FEATURE_FLAGS.CONDENSED_FILTER_BAR]) {
        return (
            <LemonSelect
                size="small"
                value={deviceTypeFilter ?? undefined}
                allowClear={true}
                onChange={(value) => setDeviceTypeFilter(value !== deviceTypeFilter ? value : null)}
                options={[
                    {
                        value: 'Desktop',
                        label: (
                            <div>
                                <IconMonitor className="mx-1" /> Desktop
                            </div>
                        ),
                        tooltip: 'Desktop devices include laptops and desktops.',
                    },
                    {
                        value: 'Mobile',
                        label: (
                            <div>
                                <IconPhone className="mx-1" /> Mobile
                            </div>
                        ),
                        tooltip: 'Mobile devices include smartphones and tablets.',
                    },
                ]}
            />
        )
    }

    return (
        <LemonSegmentedSelect
            size="small"
            value={deviceTypeFilter ?? undefined}
            onChange={(value) => setDeviceTypeFilter(value !== deviceTypeFilter ? value : null)}
            options={[
                {
                    value: 'Desktop',
                    label: <IconMonitor className="mx-1" />,
                    tooltip: 'Desktop devices include laptops and desktops.',
                },
                {
                    value: 'Mobile',
                    label: <IconPhone className="mx-1" />,
                    tooltip: 'Mobile devices include smartphones and tablets.',
                },
            ]}
        />
    )
}

const WebVitalsPercentileToggle = (): JSX.Element | null => {
    const { webVitalsPercentile, productTab } = useValues(webAnalyticsLogic)
    const { setWebVitalsPercentile } = useActions(webAnalyticsLogic)

    if (productTab !== ProductTab.WEB_VITALS) {
        return null
    }

    return (
        <LemonSegmentedSelect
            value={webVitalsPercentile}
            onChange={setWebVitalsPercentile}
            options={[
                { value: PropertyMathType.P75, label: 'P75' },
                {
                    value: PropertyMathType.P90,
                    label: (
                        <Tooltip title="P90 is recommended by the standard as a good baseline" delayMs={0}>
                            P90
                        </Tooltip>
                    ),
                },
                { value: PropertyMathType.P99, label: 'P99' },
            ]}
        />
    )
}

export const WebAnalyticsCompareFilter = (): JSX.Element | null => {
    const { compareFilter, productTab } = useValues(webAnalyticsLogic)
    const { setCompareFilter } = useActions(webAnalyticsLogic)

    if (![ProductTab.ANALYTICS, ProductTab.PAGE_REPORTS].includes(productTab)) {
        return null
    }

    return <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
}

const ShareButton = (): JSX.Element => {
    const { activePreset } = useValues(webAnalyticsFilterPresetsLogic)

    const handleShare = (): void => {
        const url = new URL(window.location.href)

        if (activePreset) {
            url.search = ''
            url.searchParams.set('presetId', activePreset.short_id)
        }

        void copyToClipboard(url.toString(), 'link')
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconLink />}
            tooltip="Share"
            tooltipPlacement="top"
            onClick={handleShare}
            data-attr="web-analytics-share-button"
        />
    )
}

function FiltersPopover(): JSX.Element {
    const [displayFilters, setDisplayFilters] = useState(false)
    const { rawWebAnalyticsFilters, conversionGoal, preAggregatedEnabled, productTab } = useValues(webAnalyticsLogic)

    const { setWebAnalyticsFilters, setConversionGoal } = useActions(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    // Toggle filters shortcut
    useAppShortcut({
        name: 'WebAnalyticsFilters',
        keybind: [[...baseModifier, 'f']],
        intent: 'Toggle filters',
        interaction: 'function',
        callback: () => setDisplayFilters((prev) => !prev),
        scope: Scene.WebAnalytics,
    })

    const showConversionGoal =
        productTab === ProductTab.ANALYTICS &&
        (!preAggregatedEnabled || featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOAL_PREAGG])

    const cohortFilterEnabled = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2]
    const taxonomicGroupTypes = getWebAnalyticsTaxonomicGroupTypes(preAggregatedEnabled ?? false, cohortFilterEnabled)
    const propertyAllowList = preAggregatedEnabled ? WEB_ANALYTICS_PROPERTY_ALLOW_LIST : undefined

    const activeFilterCount = rawWebAnalyticsFilters.length + (conversionGoal ? 1 : 0)

    const filtersContent = (
        <div className="p-3 w-96 max-w-[90vw]">
            <div className="space-y-4">
                <div>
                    <div className="text-xs font-semibold text-muted uppercase mb-2">Property filters</div>
                    <PropertyFilters
                        disablePopover
                        propertyAllowList={propertyAllowList}
                        taxonomicGroupTypes={taxonomicGroupTypes}
                        onChange={(filters) => setWebAnalyticsFilters(filters.filter(isWebAnalyticsPropertyFilter))}
                        propertyFilters={rawWebAnalyticsFilters}
                        pageKey="web-analytics"
                        eventNames={['$pageview']}
                    />
                </div>

                <LemonDivider />
                <div className="text-xs font-semibold text-muted uppercase mb-2">Device filters</div>
                <WebAnalyticsDeviceToggle />

                {showConversionGoal && (
                    <>
                        <LemonDivider />
                        <div>
                            <div className="text-xs font-semibold text-muted uppercase mb-2">Conversion goal</div>
                            <WebConversionGoal value={conversionGoal} onChange={setConversionGoal} />
                        </div>
                    </>
                )}
            </div>
        </div>
    )

    const popover = (
        <Popover
            visible={displayFilters}
            onClickOutside={() => setDisplayFilters(false)}
            placement="bottom-end"
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
                data-attr="web-analytics-unified-filters"
                onClick={() => setDisplayFilters(!displayFilters)}
            >
                Filters
            </LemonButton>
        </Popover>
    )

    return <WebAnalyticsAIFilters>{popover}</WebAnalyticsAIFilters>
}

const AddAuthorizedUrlForm = (): JSX.Element => {
    const { isProposedUrlSubmitting } = useValues(webAnalyticsLogic)
    const { cancelProposingAuthorizedUrl } = useActions(webAnalyticsLogic)

    return (
        <Form
            logic={authorizedUrlListLogic}
            props={{
                actionId: null,
                experimentId: null,
                productTourId: null,
                type: AuthorizedUrlListType.WEB_ANALYTICS,
                allowWildCards: false,
            }}
            formKey="proposedUrl"
            enableFormOnSubmit
        >
            <div className="p-2 flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
                <LemonField name="url">
                    <LemonInput
                        size="small"
                        placeholder="https://example.com"
                        autoFocus
                        data-attr="web-authorized-url-input"
                    />
                </LemonField>
                <div className="flex gap-2 justify-end">
                    <LemonButton size="small" type="secondary" onClick={cancelProposingAuthorizedUrl}>
                        Cancel
                    </LemonButton>
                    <LemonButton size="small" type="primary" htmlType="submit" loading={isProposedUrlSubmitting}>
                        Add
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}

const AddSuggestedAuthorizedUrlList = (): JSX.Element => {
    const { urlSuggestions } = useValues(webAnalyticsLogic)
    const { addAuthorizedUrl, newAuthorizedUrl } = useActions(webAnalyticsLogic)

    return (
        <div className="flex flex-col gap-1 p-1" onClick={(e) => e.stopPropagation()}>
            {urlSuggestions.length > 0 && (
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-muted px-1">Suggestions</span>
                    {urlSuggestions.slice(0, 3).map((suggestion) => (
                        <div key={suggestion.url} className="flex items-center justify-between gap-2 px-1">
                            <span className="text-xs truncate flex-1" title={suggestion.url}>
                                {suggestion.url}
                            </span>
                            <LemonButton size="xsmall" type="primary" onClick={() => addAuthorizedUrl(suggestion.url)}>
                                Add
                            </LemonButton>
                        </div>
                    ))}
                </div>
            )}
            <LemonButton size="small" icon={<IconPlus />} onClick={newAuthorizedUrl} fullWidth>
                Add authorized URL
            </LemonButton>
        </div>
    )
}

const IncompatibleFiltersWarning = (): JSX.Element | null => {
    const { hasIncompatibleFilters, incompatibleFilters, preAggregatedEnabled } = useValues(webAnalyticsLogic)
    const { removeIncompatibleFilters } = useActions(webAnalyticsLogic)

    if (!preAggregatedEnabled || !hasIncompatibleFilters) {
        return null
    }

    const filterNames = incompatibleFilters
        .map((filter) => (filter.type === PropertyFilterType.Cohort ? 'Cohort' : filter.key))
        .join(', ')

    return (
        <LemonBanner
            type="warning"
            className="mb-2"
            action={{ children: 'Remove unsupported filters', onClick: removeIncompatibleFilters }}
        >
            <div>
                <div className="font-semibold">Some filters are slowing down your queries</div>
                <div className="text-sm mt-0.5">
                    The following filters are not supported by the new query engine and are causing your queries to slow
                    down: <strong>{filterNames}</strong>
                </div>
            </div>
        </LemonBanner>
    )
}

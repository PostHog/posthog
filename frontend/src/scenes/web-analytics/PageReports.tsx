import { IconExpand45, IconTrending } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { XRayHog2 } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { IconOpenInNew, IconTableChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { addProductIntentForCrossSell, ProductIntentContext } from 'lib/utils/product-intents'
import { memo } from 'react'

import { NodeKind } from '~/queries/schema/schema-general'
import { WebStatsBreakdown } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightLogicProps, ProductKey } from '~/types'

import { pageReportsLogic } from './pageReportsLogic'
import { WebQuery } from './tiles/WebAnalyticsTile'
import { tileVisualizationLogic } from './tileVisualizationLogic'
import { LearnMorePopover } from './WebAnalyticsDashboard'
import {
    DeviceTab,
    GeographyTab,
    getWebAnalyticsBreakdownFilter,
    PathTab,
    SourceTab,
    TileId,
    webAnalyticsLogic,
} from './webAnalyticsLogic'

function PageUrlSearchHeader(): JSX.Element {
    const values = useValues(pageReportsLogic)
    const actions = useActions(pageReportsLogic)
    const { dateFilter } = useValues(webAnalyticsLogic)
    const { setDates } = useActions(webAnalyticsLogic)

    // Convert PageURL[] to LemonInputSelectOption[]
    const options = values.pageUrlSearchOptionsWithCount.map((option) => ({
        key: option.url,
        label: option.url,
        labelComponent: (
            <div className="flex justify-between items-center w-full">
                <span className="truncate">{option.url}</span>
                <span className="text-muted ml-2">{option.count.toLocaleString()}</span>
            </div>
        ),
    }))

    return (
        <div className="flex flex-col gap-2 mb-4">
            <div className="flex items-center gap-2">
                <div className="flex-1">
                    <LemonInputSelect
                        allowCustomValues={false}
                        placeholder="Click or type to see top pages"
                        loading={values.isLoading}
                        size="small"
                        mode="single"
                        value={values.pageUrl ? [values.pageUrl] : null}
                        onChange={(val: string[]) => actions.setPageUrl(val.length > 0 ? val[0] : null)}
                        options={options}
                        onInputChange={(val: string) => actions.setPageUrlSearchTerm(val)}
                        data-attr="page-url-search"
                        onFocus={() => actions.loadPages('')}
                        className="max-w-full"
                    />
                </div>
                <div>
                    <DateFilter
                        dateFrom={dateFilter.dateFrom}
                        dateTo={dateFilter.dateTo}
                        onChange={(fromDate, toDate) => setDates(fromDate, toDate)}
                    />
                </div>
            </div>
            <div className="flex items-center gap-2">
                <LemonSwitch
                    checked={values.stripQueryParams}
                    onChange={actions.toggleStripQueryParams}
                    label="Strip query parameters"
                    size="small"
                />
                <span className="text-muted text-xs">Remove query strings from URLs (e.g. "?utm_source=...")</span>
            </div>
        </div>
    )
}

// Map tile IDs to breakdown types
const tileToBreakdown: Record<
    | TileId.PAGE_REPORTS_ENTRY_PATHS
    | TileId.PAGE_REPORTS_EXIT_PATHS
    | TileId.PAGE_REPORTS_OUTBOUND_CLICKS
    | TileId.PAGE_REPORTS_CHANNELS
    | TileId.PAGE_REPORTS_REFERRERS
    | TileId.PAGE_REPORTS_DEVICE_TYPES
    | TileId.PAGE_REPORTS_BROWSERS
    | TileId.PAGE_REPORTS_OPERATING_SYSTEMS
    | TileId.PAGE_REPORTS_COUNTRIES
    | TileId.PAGE_REPORTS_REGIONS
    | TileId.PAGE_REPORTS_CITIES
    | TileId.PAGE_REPORTS_TIMEZONES
    | TileId.PAGE_REPORTS_LANGUAGES,
    WebStatsBreakdown
> = {
    // Path tiles
    [TileId.PAGE_REPORTS_ENTRY_PATHS]: WebStatsBreakdown.InitialPage,
    [TileId.PAGE_REPORTS_EXIT_PATHS]: WebStatsBreakdown.ExitPage,
    [TileId.PAGE_REPORTS_OUTBOUND_CLICKS]: WebStatsBreakdown.ExitClick,

    // Source tiles
    [TileId.PAGE_REPORTS_CHANNELS]: WebStatsBreakdown.InitialChannelType,
    [TileId.PAGE_REPORTS_REFERRERS]: WebStatsBreakdown.InitialReferringDomain,

    // Device tiles
    [TileId.PAGE_REPORTS_DEVICE_TYPES]: WebStatsBreakdown.DeviceType,
    [TileId.PAGE_REPORTS_BROWSERS]: WebStatsBreakdown.Browser,
    [TileId.PAGE_REPORTS_OPERATING_SYSTEMS]: WebStatsBreakdown.OS,

    // Geography tiles
    [TileId.PAGE_REPORTS_COUNTRIES]: WebStatsBreakdown.Country,
    [TileId.PAGE_REPORTS_REGIONS]: WebStatsBreakdown.Region,
    [TileId.PAGE_REPORTS_CITIES]: WebStatsBreakdown.City,
    [TileId.PAGE_REPORTS_TIMEZONES]: WebStatsBreakdown.Timezone,
    [TileId.PAGE_REPORTS_LANGUAGES]: WebStatsBreakdown.Language,
}

// Define SimpleTile as a standalone component outside of PageReports
interface SimpleTileProps {
    title: string
    description: string
    query: any
    tileId: TileId
    tabId: string
    pageReportsTileId?: TileId
    createInsightProps: (tileId: TileId, tabId?: string) => InsightLogicProps
    getNewInsightUrl: (tileId: TileId, tabId?: string) => string | undefined
    openModal: (tileId: TileId, tabId: string) => void
    dateFilter: any
    shouldFilterTestAccounts: boolean
    compareFilter: any
    pageUrl: string | null
}

// Memoize the component to prevent unnecessary re-renders
const SimpleTile = memo(
    ({
        title,
        description,
        query,
        tileId,
        tabId,
        pageReportsTileId,
        createInsightProps,
        getNewInsightUrl,
        openModal,
        dateFilter,
        shouldFilterTestAccounts,
        compareFilter,
        pageUrl,
    }: SimpleTileProps): JSX.Element => {
        // Use the tileVisualizationLogic with its own key - MUST be called before any conditionals
        const uniqueKey = `${pageReportsTileId || tileId}-${tabId}`
        const { visualization } = useValues(tileVisualizationLogic({ tileId: uniqueKey, tabId }))
        const { setVisualization } = useActions(tileVisualizationLogic({ tileId: uniqueKey, tabId }))

        if (!tileId || !tabId) {
            return <div>Invalid tile configuration</div>
        }

        const insightUrl = getNewInsightUrl(tileId, tabId)

        // Get the appropriate breakdown for this tile
        const breakdownBy = pageReportsTileId && tileToBreakdown[pageReportsTileId]

        // Create a processed query based on visualization type
        let processedQuery = query

        if (query && visualization === 'graph' && breakdownBy) {
            // For graph visualization, create a trends query with the appropriate breakdown
            const breakdownFilter = getWebAnalyticsBreakdownFilter(breakdownBy)

            processedQuery = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    dateRange: {
                        date_from: dateFilter.dateFrom,
                        date_to: dateFilter.dateTo,
                    },
                    interval: dateFilter.interval,
                    series: [
                        {
                            event: '$pageview',
                            kind: NodeKind.EventsNode,
                            math: 'dau',
                            name: '$pageview',
                            custom_name: 'Unique visitors',
                        },
                    ],
                    trendsFilter: {
                        display: ChartDisplayType.ActionsLineGraph,
                        showLegend: true,
                    },
                    breakdownFilter,
                    filterTestAccounts: shouldFilterTestAccounts,
                    compareFilter: compareFilter,
                    properties: query?.source?.properties || [],
                },
                hidePersonsModal: true,
                embedded: true,
            }
        }

        return (
            <div>
                <div className="flex justify-between items-center mb-1">
                    <div className="flex items-center">
                        <h3 className="text-base font-semibold m-0">{title}</h3>
                        <LearnMorePopover title={title} description={description} />
                    </div>
                    <div className="flex gap-1">
                        <LemonButton
                            icon={<IconExpand45 />}
                            size="small"
                            type="secondary"
                            onClick={() => openModal(tileId, tabId)}
                        >
                            Expand
                        </LemonButton>
                        <LemonButton
                            icon={<IconTableChart />}
                            size="small"
                            type="secondary"
                            onClick={() => setVisualization('table')}
                        >
                            Table
                        </LemonButton>
                        <LemonButton
                            icon={<IconTrending />}
                            size="small"
                            type="secondary"
                            onClick={() => setVisualization('graph')}
                        >
                            Graph
                        </LemonButton>
                        {insightUrl && (
                            <LemonButton icon={<IconOpenInNew />} size="small" type="secondary" to={insightUrl}>
                                Open
                            </LemonButton>
                        )}
                    </div>
                </div>
                <div>
                    {processedQuery && (
                        <WebQuery
                            query={processedQuery}
                            showIntervalSelect={false}
                            tileId={tileId}
                            insightProps={createInsightProps(pageReportsTileId || tileId, tabId)}
                            key={`${pageReportsTileId || tileId}-${tabId}-${pageUrl || 'none'}-${visualization}`}
                        />
                    )}
                    {!query && (
                        <div className="text-muted text-center p-4 absolute top-0 left-0 right-0 bottom-0 flex items-center justify-center bg-white bg-opacity-80 z-10">
                            No data available for this query
                        </div>
                    )}
                </div>
            </div>
        )
    }
)

// For better debugging
SimpleTile.displayName = 'SimpleTile'

export const PageReports = (): JSX.Element => {
    const { getNewInsightUrl } = useValues(webAnalyticsLogic)
    const { openModal } = useActions(webAnalyticsLogic)
    const { dateFilter, compareFilter } = useValues(webAnalyticsLogic)
    const values = useValues(pageReportsLogic)

    // Section component for consistent styling
    const Section = ({ title, children }: { title: string; children: React.ReactNode }): JSX.Element => {
        return (
            <>
                <div className="flex items-center justify-between mb-2">
                    <h2 className="text-xl font-semibold">{title}</h2>
                </div>
                {children}
                <LemonDivider className="my-4" />
            </>
        )
    }

    return (
        <div className="space-y-2 mt-2">
            <PageUrlSearchHeader />

            {!values.hasPageUrl ? (
                <ProductIntroduction
                    productName="PAGE REPORTS"
                    thingName="page report"
                    description="Page Reports provide in-depth analytics for individual pages on your website. Use the search bar above to select a specific page and see detailed metrics."
                    isEmpty={true}
                    customHog={() => <XRayHog2 alt="X-ray hedgehog" className="w-60" />}
                />
            ) : (
                <>
                    {/* Trends Section */}
                    <Section title="Trends over time">
                        <div className="w-full min-h-[350px]">
                            <WebQuery
                                query={values.combinedMetricsQuery(dateFilter, compareFilter)}
                                showIntervalSelect={true}
                                tileId={TileId.PAGE_REPORTS_COMBINED_METRICS_CHART}
                                insightProps={values.createInsightProps(
                                    TileId.PAGE_REPORTS_COMBINED_METRICS_CHART,
                                    'combined'
                                )}
                                key={`combined-metrics-${values.pageUrl}`}
                            />
                            <LemonButton
                                key="open-insight-button"
                                to={getNewInsightUrl(TileId.PAGE_REPORTS_COMBINED_METRICS_CHART, 'combined')}
                                icon={<IconOpenInNew />}
                                size="small"
                                type="secondary"
                                onClick={() => {
                                    void addProductIntentForCrossSell({
                                        from: ProductKey.WEB_ANALYTICS,
                                        to: ProductKey.PRODUCT_ANALYTICS,
                                        intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                                    })
                                }}
                            >
                                Open as new Insight
                            </LemonButton>
                        </div>
                    </Section>

                    {/* Page Paths Analysis Section */}
                    <Section title="Page Paths Analysis">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <SimpleTile
                                title="Entry Paths"
                                description="How users arrive at this page"
                                query={values.queries.entryPathsQuery}
                                tileId={TileId.PAGE_REPORTS_ENTRY_PATHS}
                                tabId={PathTab.INITIAL_PATH}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Exit Paths"
                                description="Where users go after viewing this page"
                                query={values.queries.exitPathsQuery}
                                tileId={TileId.PAGE_REPORTS_EXIT_PATHS}
                                tabId={PathTab.END_PATH}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Outbound Clicks"
                                description="External links users click on this page"
                                query={values.queries.outboundClicksQuery}
                                tileId={TileId.PAGE_REPORTS_OUTBOUND_CLICKS}
                                tabId={PathTab.EXIT_CLICK}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />
                        </div>
                    </Section>

                    {/* Traffic Sources Section */}
                    <Section title="Traffic Sources">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                            <SimpleTile
                                title="Channels"
                                description="Marketing channels bringing users to this page"
                                query={values.queries.channelsQuery}
                                tileId={TileId.PAGE_REPORTS_CHANNELS}
                                tabId={SourceTab.CHANNEL}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Referrers"
                                description="Websites referring traffic to this page"
                                query={values.queries.referrersQuery}
                                tileId={TileId.PAGE_REPORTS_REFERRERS}
                                tabId={SourceTab.REFERRING_DOMAIN}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />
                        </div>
                    </Section>

                    {/* Device Information Section */}
                    <Section title="Device Information">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <SimpleTile
                                title="Device Types"
                                description="Types of devices used to access this page"
                                query={values.queries.deviceTypeQuery}
                                tileId={TileId.PAGE_REPORTS_DEVICE_TYPES}
                                tabId={DeviceTab.DEVICE_TYPE}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Browsers"
                                description="Browsers used to access this page"
                                query={values.queries.browserQuery}
                                tileId={TileId.PAGE_REPORTS_BROWSERS}
                                tabId={DeviceTab.BROWSER}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Operating Systems"
                                description="Operating systems used to access this page"
                                query={values.queries.osQuery}
                                tileId={TileId.PAGE_REPORTS_OPERATING_SYSTEMS}
                                tabId={DeviceTab.OS}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />
                        </div>
                    </Section>

                    {/* Geography Section */}
                    <Section title="Geography">
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <SimpleTile
                                title="Countries"
                                description="Countries where users access this page from"
                                query={values.queries.countriesQuery}
                                tileId={TileId.PAGE_REPORTS_COUNTRIES}
                                tabId={GeographyTab.COUNTRIES}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Regions"
                                description="Regions where users access this page from"
                                query={values.queries.regionsQuery}
                                tileId={TileId.PAGE_REPORTS_REGIONS}
                                tabId={GeographyTab.REGIONS}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Cities"
                                description="Cities where users access this page from"
                                query={values.queries.citiesQuery}
                                tileId={TileId.PAGE_REPORTS_CITIES}
                                tabId={GeographyTab.CITIES}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2">
                            <SimpleTile
                                title="Timezones"
                                description="Timezones where users access this page from"
                                query={values.queries.timezonesQuery}
                                tileId={TileId.PAGE_REPORTS_TIMEZONES}
                                tabId={GeographyTab.TIMEZONES}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Languages"
                                description="Languages of users accessing this page"
                                query={values.queries.languagesQuery}
                                tileId={TileId.PAGE_REPORTS_LANGUAGES}
                                tabId={GeographyTab.LANGUAGES}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={compareFilter}
                                pageUrl={values.pageUrl}
                            />
                        </div>
                    </Section>
                </>
            )}
        </div>
    )
}

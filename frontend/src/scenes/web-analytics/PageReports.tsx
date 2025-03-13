import { IconExpand45, IconTrending } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { XRayHog2 } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { IconOpenInNew, IconTableChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { addProductIntentForCrossSell, ProductIntentContext } from 'lib/utils/product-intents'
import { memo } from 'react'

import { NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import { WebStatsBreakdown } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightLogicProps, ProductKey } from '~/types'

import { pageReportsLogic, PageReportsTileId } from './pageReportsLogic'
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
    TileVisualizationOption,
    webAnalyticsLogic,
} from './webAnalyticsLogic'

// Extended interface for pageReportsLogic values
interface PageReportsLogicValues {
    pageUrl: string | null
    pageUrlSearchTerm: string
    isInitialLoad: boolean
    pagesLoading: boolean
    hasPageUrl: boolean
    isLoading: boolean
    pageUrlSearchOptionsWithCount: { url: string; count: number }[]
    stripQueryParams: boolean
    // Queries object
    queries: {
        entryPathsQuery: any
        exitPathsQuery: any
        outboundClicksQuery: any
        channelsQuery: any
        referrersQuery: any
        deviceTypeQuery: any
        browserQuery: any
        osQuery: any
        countriesQuery: any
        regionsQuery: any
        citiesQuery: any
        timezonesQuery: any
        languagesQuery: any
    }
    // Helper functions
    createInsightProps: (tileId: TileId | PageReportsTileId, tabId?: string) => InsightLogicProps
    // Combined metrics query
    combinedMetricsQuery: any
    // Visualization options
    getTileVisualization: (tileId: PageReportsTileId) => TileVisualizationOption
    tileVisualizations: Record<PageReportsTileId, TileVisualizationOption>
    // Get query for a specific tile
    getQueryForTile: (tileId: PageReportsTileId) => QuerySchema | undefined
    // Date filter
    dateFilter: any
    // Compare filter
    compareFilter: any
    // Filter test accounts
    shouldFilterTestAccounts: boolean
}

function PageUrlSearchHeader(): JSX.Element {
    const values = useValues(pageReportsLogic) as unknown as PageReportsLogicValues
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
const tileToBreakdown: Record<PageReportsTileId, WebStatsBreakdown> = {
    // Path tiles
    [PageReportsTileId.ENTRY_PATHS]: WebStatsBreakdown.InitialPage,
    [PageReportsTileId.EXIT_PATHS]: WebStatsBreakdown.ExitPage,
    [PageReportsTileId.OUTBOUND_CLICKS]: WebStatsBreakdown.ExitClick,

    // Source tiles
    [PageReportsTileId.CHANNELS]: WebStatsBreakdown.InitialChannelType,
    [PageReportsTileId.REFERRERS]: WebStatsBreakdown.InitialReferringDomain,

    // Device tiles
    [PageReportsTileId.DEVICE_TYPES]: WebStatsBreakdown.DeviceType,
    [PageReportsTileId.BROWSERS]: WebStatsBreakdown.Browser,
    [PageReportsTileId.OPERATING_SYSTEMS]: WebStatsBreakdown.OS,

    // Geography tiles
    [PageReportsTileId.COUNTRIES]: WebStatsBreakdown.Country,
    [PageReportsTileId.REGIONS]: WebStatsBreakdown.Region,
    [PageReportsTileId.CITIES]: WebStatsBreakdown.City,
    [PageReportsTileId.TIMEZONES]: WebStatsBreakdown.Timezone,
    [PageReportsTileId.LANGUAGES]: WebStatsBreakdown.Language,
}

// Define SimpleTile as a standalone component outside of PageReports
interface SimpleTileProps {
    title: string
    description: string
    query: any
    tileId: TileId
    tabId: string
    pageReportsTileId?: PageReportsTileId
    createInsightProps: (tileId: TileId | PageReportsTileId, tabId?: string) => InsightLogicProps
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
                        {pageReportsTileId && (
                            <LemonSegmentedButton
                                value={visualization}
                                onChange={(value) => setVisualization(value as TileVisualizationOption)}
                                options={[
                                    {
                                        value: 'table',
                                        icon: <IconTableChart />,
                                        tooltip: 'Show as table',
                                    },
                                    {
                                        value: 'graph',
                                        icon: <IconTrending />,
                                        tooltip: 'Show as graph',
                                    },
                                ]}
                                size="small"
                            />
                        )}
                        {insightUrl && (
                            <LemonButton
                                icon={<IconOpenInNew />}
                                size="small"
                                to={insightUrl}
                                onClick={() => {
                                    void addProductIntentForCrossSell({
                                        from: ProductKey.WEB_ANALYTICS,
                                        to: ProductKey.PRODUCT_ANALYTICS,
                                        intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                                    })
                                }}
                                tooltip="Open as new Insight"
                            />
                        )}
                        <LemonButton
                            icon={<IconExpand45 />}
                            size="small"
                            onClick={() => openModal(tileId, tabId)}
                            tooltip="Show more"
                        />
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
    const values = useValues(pageReportsLogic) as unknown as PageReportsLogicValues

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
                                query={values.combinedMetricsQuery}
                                showIntervalSelect={true}
                                tileId={TileId.GRAPHS}
                                insightProps={values.createInsightProps(TileId.GRAPHS, 'combined')}
                                key={`combined-metrics-${values.pageUrl}`}
                            />
                            <LemonButton
                                key="open-insight-button"
                                to={getNewInsightUrl(TileId.GRAPHS, 'combined')}
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
                                tileId={TileId.PATHS}
                                tabId={PathTab.INITIAL_PATH}
                                pageReportsTileId={PageReportsTileId.ENTRY_PATHS}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Exit Paths"
                                description="Where users go after viewing this page"
                                query={values.queries.exitPathsQuery}
                                tileId={TileId.PATHS}
                                tabId={PathTab.END_PATH}
                                pageReportsTileId={PageReportsTileId.EXIT_PATHS}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Outbound Clicks"
                                description="External links users click on this page"
                                query={values.queries.outboundClicksQuery}
                                tileId={TileId.PATHS}
                                tabId={PathTab.EXIT_CLICK}
                                pageReportsTileId={PageReportsTileId.OUTBOUND_CLICKS}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
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
                                tileId={TileId.SOURCES}
                                tabId={SourceTab.CHANNEL}
                                pageReportsTileId={PageReportsTileId.CHANNELS}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Referrers"
                                description="Websites referring traffic to this page"
                                query={values.queries.referrersQuery}
                                tileId={TileId.SOURCES}
                                tabId={SourceTab.REFERRING_DOMAIN}
                                pageReportsTileId={PageReportsTileId.REFERRERS}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
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
                                tileId={TileId.DEVICES}
                                tabId={DeviceTab.DEVICE_TYPE}
                                pageReportsTileId={PageReportsTileId.DEVICE_TYPES}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Browsers"
                                description="Browsers used to access this page"
                                query={values.queries.browserQuery}
                                tileId={TileId.DEVICES}
                                tabId={DeviceTab.BROWSER}
                                pageReportsTileId={PageReportsTileId.BROWSERS}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Operating Systems"
                                description="Operating systems used to access this page"
                                query={values.queries.osQuery}
                                tileId={TileId.DEVICES}
                                tabId={DeviceTab.OS}
                                pageReportsTileId={PageReportsTileId.OPERATING_SYSTEMS}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
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
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.COUNTRIES}
                                pageReportsTileId={PageReportsTileId.COUNTRIES}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Regions"
                                description="Regions where users access this page from"
                                query={values.queries.regionsQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.REGIONS}
                                pageReportsTileId={PageReportsTileId.REGIONS}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Cities"
                                description="Cities where users access this page from"
                                query={values.queries.citiesQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.CITIES}
                                pageReportsTileId={PageReportsTileId.CITIES}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
                                pageUrl={values.pageUrl}
                            />
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2">
                            <SimpleTile
                                title="Timezones"
                                description="Timezones where users access this page from"
                                query={values.queries.timezonesQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.TIMEZONES}
                                pageReportsTileId={PageReportsTileId.TIMEZONES}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
                                pageUrl={values.pageUrl}
                            />

                            <SimpleTile
                                title="Languages"
                                description="Languages of users accessing this page"
                                query={values.queries.languagesQuery}
                                tileId={TileId.GEOGRAPHY}
                                tabId={GeographyTab.LANGUAGES}
                                pageReportsTileId={PageReportsTileId.LANGUAGES}
                                createInsightProps={values.createInsightProps}
                                getNewInsightUrl={getNewInsightUrl}
                                openModal={openModal}
                                dateFilter={values.dateFilter}
                                shouldFilterTestAccounts={values.shouldFilterTestAccounts}
                                compareFilter={values.compareFilter}
                                pageUrl={values.pageUrl}
                            />
                        </div>
                    </Section>
                </>
            )}
        </div>
    )
}

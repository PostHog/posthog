import { IconExpand45, IconInfo } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, InsightLogicProps } from '~/types'

import { WebQuery } from './tiles/WebAnalyticsTile'
import {
    DeviceTab,
    GeographyTab,
    PathTab,
    SourceTab,
    TabsTile,
    TileId,
    WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    webAnalyticsLogic,
} from './webAnalyticsLogic'

export const PageReports = (): JSX.Element => {
    const { webAnalyticsFilters, tiles, dateFilter, shouldFilterTestAccounts, compareFilter } =
        useValues(webAnalyticsLogic)
    const { openModal } = useActions(webAnalyticsLogic)

    // Check if a specific page is selected in the filters
    const hasPageFilter = webAnalyticsFilters.some(
        (filter) => filter.key === '$pathname' || filter.key === '$current_url'
    )

    // Get the selected page path from filters
    const selectedPage = webAnalyticsFilters.find(
        (filter) => filter.key === '$pathname' || filter.key === '$current_url'
    )?.value as string | undefined

    // Find the tiles
    const pathsTile = tiles.find((tile) => tile.tileId === TileId.PATHS) as TabsTile | undefined
    const sourcesTile = tiles.find((tile) => tile.tileId === TileId.SOURCES) as TabsTile | undefined
    const devicesTile = tiles.find((tile) => tile.tileId === TileId.DEVICES) as TabsTile | undefined
    const geographyTile = tiles.find((tile) => tile.tileId === TileId.GEOGRAPHY) as TabsTile | undefined

    // Get the queries for each tab
    const entryPathsQuery = pathsTile?.tabs.find((tab) => tab.id === PathTab.INITIAL_PATH)?.query
    const exitPathsQuery = pathsTile?.tabs.find((tab) => tab.id === PathTab.END_PATH)?.query
    const outboundClicksQuery = pathsTile?.tabs.find((tab) => tab.id === PathTab.EXIT_CLICK)?.query

    // Get source queries
    const channelsQuery = sourcesTile?.tabs.find((tab) => tab.id === SourceTab.CHANNEL)?.query
    const referrersQuery = sourcesTile?.tabs.find((tab) => tab.id === SourceTab.REFERRING_DOMAIN)?.query

    // Get device queries
    const deviceTypeQuery = devicesTile?.tabs.find((tab) => tab.id === DeviceTab.DEVICE_TYPE)?.query
    const browserQuery = devicesTile?.tabs.find((tab) => tab.id === DeviceTab.BROWSER)?.query
    const osQuery = devicesTile?.tabs.find((tab) => tab.id === DeviceTab.OS)?.query

    // Get geography queries
    const countriesQuery = geographyTile?.tabs.find((tab) => tab.id === GeographyTab.COUNTRIES)?.query
    const regionsQuery = geographyTile?.tabs.find((tab) => tab.id === GeographyTab.REGIONS)?.query
    const citiesQuery = geographyTile?.tabs.find((tab) => tab.id === GeographyTab.CITIES)?.query
    const timezonesQuery = geographyTile?.tabs.find((tab) => tab.id === GeographyTab.TIMEZONES)?.query
    const languagesQuery = geographyTile?.tabs.find((tab) => tab.id === GeographyTab.LANGUAGES)?.query

    // Create insight props for the queries
    const createInsightProps = (tileId: TileId, tabId?: string): InsightLogicProps => ({
        dashboardItemId: `new-${tileId}${tabId ? `-${tabId}` : ''}`,
        loadPriority: 0,
        dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })

    // Create a combined query for all three metrics
    const combinedMetricsQuery: InsightVizNode<TrendsQuery> = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    event: '$pageview',
                    kind: NodeKind.EventsNode,
                    math: BaseMathType.UniqueUsers,
                    name: '$pageview',
                    custom_name: 'Unique visitors',
                },
                {
                    event: '$pageview',
                    kind: NodeKind.EventsNode,
                    math: BaseMathType.TotalCount,
                    name: '$pageview',
                    custom_name: 'Page views',
                },
                {
                    event: '$pageview',
                    kind: NodeKind.EventsNode,
                    math: BaseMathType.UniqueSessions,
                    name: '$pageview',
                    custom_name: 'Sessions',
                },
            ],
            interval: dateFilter.interval,
            dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                showLegend: true,
            },
            compareFilter,
            filterTestAccounts: shouldFilterTestAccounts,
            properties: webAnalyticsFilters,
        },
        hidePersonsModal: true,
        embedded: true,
    }

    // Section component for consistent styling
    const Section = ({ title, children }: { title: string; children: React.ReactNode }): JSX.Element => (
        <>
            <div className="flex items-center gap-2 mb-2">
                <h2 className="text-2xl font-bold">{title}</h2>
                <IconInfo className="text-muted text-xl" />
            </div>
            {children}
            <LemonDivider className="my-6" />
        </>
    )

    // Card component for consistent styling
    const Card = ({
        title,
        description,
        query,
        tileId,
        tabId,
    }: {
        title: string
        description: string
        query: any
        tileId: TileId
        tabId: string
    }): JSX.Element => (
        <div className="border rounded bg-white">
            <div className="flex justify-between items-center p-4 border-b">
                <h3 className="text-xl font-bold">{title}</h3>
                <LemonButton icon={<IconExpand45 />} size="small" onClick={() => openModal(tileId, tabId)} />
            </div>
            <div className="p-4">
                <p className="text-sm text-muted mb-4">{description}</p>
                {query && (
                    <div className="overflow-x-auto">
                        <WebQuery
                            query={query}
                            showIntervalSelect={false}
                            tileId={tileId}
                            insightProps={createInsightProps(tileId, tabId)}
                        />
                    </div>
                )}
            </div>
        </div>
    )

    return (
        <div className="space-y-4 mt-4">
            {!hasPageFilter && (
                <LemonBanner type="info" className="mb-4">
                    <h3 className="font-semibold">No specific page selected</h3>
                    <p>
                        Select a specific page using the filters above to see detailed analytics for that page.
                        Currently showing aggregated data across all pages.
                    </p>
                </LemonBanner>
            )}

            {hasPageFilter && (
                <LemonBanner type="success" className="mb-4">
                    <h3 className="font-semibold">Page Report: {selectedPage}</h3>
                </LemonBanner>
            )}

            {/* Trends Section */}
            <Section title="Page Performance">
                <div className="border rounded bg-white">
                    <div className="flex justify-between items-center p-4 border-b">
                        <h3 className="text-xl font-bold">Page Performance Trends</h3>
                        <LemonButton
                            icon={<IconExpand45 />}
                            size="small"
                            onClick={() => openModal(TileId.GRAPHS, 'combined')}
                        >
                            Show more
                        </LemonButton>
                    </div>
                    <div className="p-4">
                        <div className="w-full min-h-[400px]">
                            <WebQuery
                                query={combinedMetricsQuery}
                                showIntervalSelect={true}
                                tileId={TileId.GRAPHS}
                                insightProps={createInsightProps(TileId.GRAPHS, 'combined')}
                            />
                        </div>
                    </div>
                </div>
            </Section>

            {/* Page Paths Analysis Section */}
            <Section title="Page Paths Analysis">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <Card
                        title="Entry Paths"
                        description="How users arrive at this page"
                        query={entryPathsQuery}
                        tileId={TileId.PATHS}
                        tabId={PathTab.INITIAL_PATH}
                    />

                    <Card
                        title="Exit Paths"
                        description="Where users go after viewing this page"
                        query={exitPathsQuery}
                        tileId={TileId.PATHS}
                        tabId={PathTab.END_PATH}
                    />

                    <Card
                        title="Outbound Clicks"
                        description="External links users click on this page"
                        query={outboundClicksQuery}
                        tileId={TileId.PATHS}
                        tabId={PathTab.EXIT_CLICK}
                    />
                </div>
            </Section>

            {/* Traffic Sources Section */}
            <Section title="Traffic Sources">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <Card
                        title="Channels"
                        description="Marketing channels bringing users to this page"
                        query={channelsQuery}
                        tileId={TileId.SOURCES}
                        tabId={SourceTab.CHANNEL}
                    />

                    <Card
                        title="Referrers"
                        description="Websites referring traffic to this page"
                        query={referrersQuery}
                        tileId={TileId.SOURCES}
                        tabId={SourceTab.REFERRING_DOMAIN}
                    />
                </div>
            </Section>

            {/* Device Information Section */}
            <Section title="Device Information">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <Card
                        title="Device Types"
                        description="Types of devices used to access this page"
                        query={deviceTypeQuery}
                        tileId={TileId.DEVICES}
                        tabId={DeviceTab.DEVICE_TYPE}
                    />

                    <Card
                        title="Browsers"
                        description="Browsers used to access this page"
                        query={browserQuery}
                        tileId={TileId.DEVICES}
                        tabId={DeviceTab.BROWSER}
                    />

                    <Card
                        title="Operating Systems"
                        description="Operating systems used to access this page"
                        query={osQuery}
                        tileId={TileId.DEVICES}
                        tabId={DeviceTab.OS}
                    />
                </div>
            </Section>

            {/* Geography Section */}
            <Section title="Geography">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <Card
                        title="Countries"
                        description="Countries where users access this page from"
                        query={countriesQuery}
                        tileId={TileId.GEOGRAPHY}
                        tabId={GeographyTab.COUNTRIES}
                    />

                    <Card
                        title="Regions"
                        description="Regions where users access this page from"
                        query={regionsQuery}
                        tileId={TileId.GEOGRAPHY}
                        tabId={GeographyTab.REGIONS}
                    />

                    <Card
                        title="Cities"
                        description="Cities where users access this page from"
                        query={citiesQuery}
                        tileId={TileId.GEOGRAPHY}
                        tabId={GeographyTab.CITIES}
                    />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                    <Card
                        title="Timezones"
                        description="Timezones where users access this page from"
                        query={timezonesQuery}
                        tileId={TileId.GEOGRAPHY}
                        tabId={GeographyTab.TIMEZONES}
                    />

                    <Card
                        title="Languages"
                        description="Languages of users accessing this page"
                        query={languagesQuery}
                        tileId={TileId.GEOGRAPHY}
                        tabId={GeographyTab.LANGUAGES}
                    />
                </div>
            </Section>
        </div>
    )
}

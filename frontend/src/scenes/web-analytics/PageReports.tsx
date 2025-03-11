import { IconExpand45 } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'
import { BaseMathType } from '~/types'

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

// Reusable tile component
interface AnalyticsTileProps {
    title: string
    description?: string
    query: any
    tileId: TileId
    tabId: string
    className?: string
}

const AnalyticsTile: React.FC<AnalyticsTileProps> = ({ title, description, query, tileId, tabId, className = '' }) => {
    const { openModal } = useActions(webAnalyticsLogic)

    // Create insight props for the query
    const createInsightProps = (tileId: TileId, tabId?: string): InsightLogicProps => ({
        dashboardItemId: `new-${tileId}${tabId ? `-${tabId}` : ''}`,
        loadPriority: 0,
        dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })

    return (
        <div className={`border rounded p-4 bg-white ${className}`}>
            <div className="flex justify-between items-center mb-2">
                <h3 className="font-semibold">{title}</h3>
                <LemonButton icon={<IconExpand45 />} size="small" onClick={() => openModal(tileId, tabId)} />
            </div>
            {description && <p className="text-sm text-muted mb-2">{description}</p>}
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
    )
}

export const PageReports = (): JSX.Element => {
    const { webAnalyticsFilters, tiles, dateFilter, shouldFilterTestAccounts } = useValues(webAnalyticsLogic)

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
    const combinedMetricsQuery = {
        kind: NodeKind.InsightVizNode,
        embedded: true,
        hidePersonsModal: true,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                // Unique visitors series
                {
                    event: '$pageview',
                    kind: NodeKind.EventsNode,
                    math: BaseMathType.UniqueUsers,
                    name: '$pageview',
                    custom_name: 'Unique visitors',
                },
                // Page views series
                {
                    event: '$pageview',
                    kind: NodeKind.EventsNode,
                    math: BaseMathType.TotalCount,
                    name: '$pageview',
                    custom_name: 'Page views',
                },
                // Sessions series
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
                display: 'ActionsLineGraph',
                showLegend: true,
            },
            filterTestAccounts: shouldFilterTestAccounts,
            properties: webAnalyticsFilters,
        },
    }

    return (
        <div className="space-y-6 mt-4">
            {!hasPageFilter && (
                <LemonBanner type="info">
                    <h3 className="font-semibold">No specific page selected</h3>
                    <p>
                        Select a specific page using the filters above to see detailed analytics for that page.
                        Currently showing aggregated data across all pages.
                    </p>
                </LemonBanner>
            )}

            {hasPageFilter && (
                <LemonBanner type="success">
                    <h3 className="font-semibold">Page Report: {selectedPage}</h3>
                    <p>
                        Showing detailed analytics for the selected page. Use the filters above to change the date range
                        or add additional filters.
                    </p>
                </LemonBanner>
            )}

            {/* Performance Metrics Section */}
            <div>
                <h2 className="text-lg font-semibold mb-4">Performance Metrics</h2>
                <div className="w-full min-h-[400px]">
                    <WebQuery
                        query={combinedMetricsQuery}
                        showIntervalSelect={true}
                        tileId={TileId.GRAPHS}
                        insightProps={createInsightProps(TileId.GRAPHS, 'combined')}
                    />
                </div>
            </div>

            <LemonDivider />

            {/* Page Paths Analysis Section */}
            <div>
                <h2 className="text-lg font-semibold mb-4">Page Paths Analysis</h2>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <AnalyticsTile
                        title="Entry Paths"
                        description="How users arrive at this page"
                        query={entryPathsQuery}
                        tileId={TileId.PATHS}
                        tabId={PathTab.INITIAL_PATH}
                    />

                    <AnalyticsTile
                        title="Exit Paths"
                        description="Where users go after viewing this page"
                        query={exitPathsQuery}
                        tileId={TileId.PATHS}
                        tabId={PathTab.END_PATH}
                    />

                    <AnalyticsTile
                        title="Outbound Clicks"
                        description="External links users click on this page"
                        query={outboundClicksQuery}
                        tileId={TileId.PATHS}
                        tabId={PathTab.EXIT_CLICK}
                    />
                </div>
            </div>

            <LemonDivider />

            {/* Traffic Sources Section */}
            <div>
                <h2 className="text-lg font-semibold mb-4">Traffic Sources</h2>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <AnalyticsTile
                        title="Channels"
                        description="Marketing channels bringing users to this page"
                        query={channelsQuery}
                        tileId={TileId.SOURCES}
                        tabId={SourceTab.CHANNEL}
                    />

                    <AnalyticsTile
                        title="Referrers"
                        description="Websites referring traffic to this page"
                        query={referrersQuery}
                        tileId={TileId.SOURCES}
                        tabId={SourceTab.REFERRING_DOMAIN}
                    />
                </div>
            </div>

            <LemonDivider />

            {/* Device Information Section */}
            <div>
                <h2 className="text-lg font-semibold mb-4">Device Information</h2>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <AnalyticsTile
                        title="Device Types"
                        description="Types of devices used to access this page"
                        query={deviceTypeQuery}
                        tileId={TileId.DEVICES}
                        tabId={DeviceTab.DEVICE_TYPE}
                    />

                    <AnalyticsTile
                        title="Browsers"
                        description="Browsers used to access this page"
                        query={browserQuery}
                        tileId={TileId.DEVICES}
                        tabId={DeviceTab.BROWSER}
                    />

                    <AnalyticsTile
                        title="Operating Systems"
                        description="Operating systems used to access this page"
                        query={osQuery}
                        tileId={TileId.DEVICES}
                        tabId={DeviceTab.OS}
                    />
                </div>
            </div>

            <LemonDivider />

            {/* Geography Section */}
            <div>
                <h2 className="text-lg font-semibold mb-4">Geography</h2>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <AnalyticsTile
                        title="Countries"
                        description="Countries of visitors"
                        query={countriesQuery}
                        tileId={TileId.GEOGRAPHY}
                        tabId={GeographyTab.COUNTRIES}
                    />

                    <AnalyticsTile
                        title="Regions"
                        description="Regions of visitors"
                        query={regionsQuery}
                        tileId={TileId.GEOGRAPHY}
                        tabId={GeographyTab.REGIONS}
                    />

                    <AnalyticsTile
                        title="Cities"
                        description="Cities of visitors"
                        query={citiesQuery}
                        tileId={TileId.GEOGRAPHY}
                        tabId={GeographyTab.CITIES}
                    />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                    <AnalyticsTile
                        title="Timezones"
                        description="Timezones of visitors"
                        query={timezonesQuery}
                        tileId={TileId.GEOGRAPHY}
                        tabId={GeographyTab.TIMEZONES}
                    />

                    <AnalyticsTile
                        title="Languages"
                        description="Languages of visitors"
                        query={languagesQuery}
                        tileId={TileId.GEOGRAPHY}
                        tabId={GeographyTab.LANGUAGES}
                    />
                </div>
            </div>
        </div>
    )
}

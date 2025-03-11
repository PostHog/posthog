import { IconExpand45 } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

import { InsightLogicProps } from '~/types'

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
    const { webAnalyticsFilters, tiles } = useValues(webAnalyticsLogic)
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

    // Create insight props for the queries
    const createInsightProps = (tileId: TileId, tabId?: string): InsightLogicProps => ({
        dashboardItemId: `new-${tileId}${tabId ? `-${tabId}` : ''}`,
        loadPriority: 0,
        dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })

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

            {/* Page Paths Analysis Section */}
            <div className="space-y-4">
                <h2 className="text-lg font-semibold">Page Paths Analysis</h2>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {/* Entry Paths Table */}
                    <div className="border rounded p-4 bg-white">
                        <div className="flex justify-between items-center mb-2">
                            <h3 className="font-semibold">Entry Paths</h3>
                            <LemonButton
                                icon={<IconExpand45 />}
                                size="small"
                                onClick={() => openModal(TileId.PATHS, PathTab.INITIAL_PATH)}
                            />
                        </div>
                        <p className="text-sm text-muted mb-2">How users arrive at this page</p>
                        {entryPathsQuery && (
                            <div className="overflow-x-auto">
                                <WebQuery
                                    query={entryPathsQuery}
                                    showIntervalSelect={false}
                                    tileId={TileId.PATHS}
                                    insightProps={createInsightProps(TileId.PATHS, PathTab.INITIAL_PATH)}
                                />
                            </div>
                        )}
                    </div>

                    {/* Exit Paths Table */}
                    <div className="border rounded p-4 bg-white">
                        <div className="flex justify-between items-center mb-2">
                            <h3 className="font-semibold">Exit Paths</h3>
                            <LemonButton
                                icon={<IconExpand45 />}
                                size="small"
                                onClick={() => openModal(TileId.PATHS, PathTab.END_PATH)}
                            />
                        </div>
                        <p className="text-sm text-muted mb-2">Where users go after viewing this page</p>
                        {exitPathsQuery && (
                            <div className="overflow-x-auto">
                                <WebQuery
                                    query={exitPathsQuery}
                                    showIntervalSelect={false}
                                    tileId={TileId.PATHS}
                                    insightProps={createInsightProps(TileId.PATHS, PathTab.END_PATH)}
                                />
                            </div>
                        )}
                    </div>

                    {/* Outbound Clicks Table */}
                    <div className="border rounded p-4 bg-white">
                        <div className="flex justify-between items-center mb-2">
                            <h3 className="font-semibold">Outbound Clicks</h3>
                            <LemonButton
                                icon={<IconExpand45 />}
                                size="small"
                                onClick={() => openModal(TileId.PATHS, PathTab.EXIT_CLICK)}
                            />
                        </div>
                        <p className="text-sm text-muted mb-2">External links users click on this page</p>
                        {outboundClicksQuery && (
                            <div className="overflow-x-auto">
                                <WebQuery
                                    query={outboundClicksQuery}
                                    showIntervalSelect={false}
                                    tileId={TileId.PATHS}
                                    insightProps={createInsightProps(TileId.PATHS, PathTab.EXIT_CLICK)}
                                />
                            </div>
                        )}
                    </div>
                </div>
            </div>

            <LemonDivider />

            {/* Traffic Sources Section */}
            <div className="space-y-4">
                <h2 className="text-lg font-semibold">Traffic Sources</h2>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Channels Table */}
                    <div className="border rounded p-4 bg-white">
                        <div className="flex justify-between items-center mb-2">
                            <h3 className="font-semibold">Channels</h3>
                            <LemonButton
                                icon={<IconExpand45 />}
                                size="small"
                                onClick={() => openModal(TileId.SOURCES, SourceTab.CHANNEL)}
                            />
                        </div>
                        <p className="text-sm text-muted mb-2">Marketing channels bringing traffic to this page</p>
                        {channelsQuery && (
                            <div className="overflow-x-auto">
                                <WebQuery
                                    query={channelsQuery}
                                    showIntervalSelect={false}
                                    tileId={TileId.SOURCES}
                                    insightProps={createInsightProps(TileId.SOURCES, SourceTab.CHANNEL)}
                                />
                            </div>
                        )}
                    </div>

                    {/* Referrers Table */}
                    <div className="border rounded p-4 bg-white">
                        <div className="flex justify-between items-center mb-2">
                            <h3 className="font-semibold">Referrers</h3>
                            <LemonButton
                                icon={<IconExpand45 />}
                                size="small"
                                onClick={() => openModal(TileId.SOURCES, SourceTab.REFERRING_DOMAIN)}
                            />
                        </div>
                        <p className="text-sm text-muted mb-2">Websites referring traffic to this page</p>
                        {referrersQuery && (
                            <div className="overflow-x-auto">
                                <WebQuery
                                    query={referrersQuery}
                                    showIntervalSelect={false}
                                    tileId={TileId.SOURCES}
                                    insightProps={createInsightProps(TileId.SOURCES, SourceTab.REFERRING_DOMAIN)}
                                />
                            </div>
                        )}
                    </div>
                </div>
            </div>

            <LemonDivider />

            {/* Device & Geography Section */}
            <div className="space-y-4">
                <h2 className="text-lg font-semibold">Visitor Information</h2>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    {/* Device Type Table */}
                    <div className="border rounded p-4 bg-white">
                        <div className="flex justify-between items-center mb-2">
                            <h3 className="font-semibold">Device Types</h3>
                            <LemonButton
                                icon={<IconExpand45 />}
                                size="small"
                                onClick={() => openModal(TileId.DEVICES, DeviceTab.DEVICE_TYPE)}
                            />
                        </div>
                        <p className="text-sm text-muted mb-2">Types of devices used to access this page</p>
                        {deviceTypeQuery && (
                            <div className="overflow-x-auto">
                                <WebQuery
                                    query={deviceTypeQuery}
                                    showIntervalSelect={false}
                                    tileId={TileId.DEVICES}
                                    insightProps={createInsightProps(TileId.DEVICES, DeviceTab.DEVICE_TYPE)}
                                />
                            </div>
                        )}
                    </div>

                    {/* Browser Table */}
                    <div className="border rounded p-4 bg-white">
                        <div className="flex justify-between items-center mb-2">
                            <h3 className="font-semibold">Browsers</h3>
                            <LemonButton
                                icon={<IconExpand45 />}
                                size="small"
                                onClick={() => openModal(TileId.DEVICES, DeviceTab.BROWSER)}
                            />
                        </div>
                        <p className="text-sm text-muted mb-2">Browsers used to access this page</p>
                        {browserQuery && (
                            <div className="overflow-x-auto">
                                <WebQuery
                                    query={browserQuery}
                                    showIntervalSelect={false}
                                    tileId={TileId.DEVICES}
                                    insightProps={createInsightProps(TileId.DEVICES, DeviceTab.BROWSER)}
                                />
                            </div>
                        )}
                    </div>

                    {/* OS Table */}
                    <div className="border rounded p-4 bg-white">
                        <div className="flex justify-between items-center mb-2">
                            <h3 className="font-semibold">Operating Systems</h3>
                            <LemonButton
                                icon={<IconExpand45 />}
                                size="small"
                                onClick={() => openModal(TileId.DEVICES, DeviceTab.OS)}
                            />
                        </div>
                        <p className="text-sm text-muted mb-2">Operating systems used to access this page</p>
                        {osQuery && (
                            <div className="overflow-x-auto">
                                <WebQuery
                                    query={osQuery}
                                    showIntervalSelect={false}
                                    tileId={TileId.DEVICES}
                                    insightProps={createInsightProps(TileId.DEVICES, DeviceTab.OS)}
                                />
                            </div>
                        )}
                    </div>

                    {/* Countries Table */}
                    <div className="border rounded p-4 bg-white">
                        <div className="flex justify-between items-center mb-2">
                            <h3 className="font-semibold">Countries</h3>
                            <LemonButton
                                icon={<IconExpand45 />}
                                size="small"
                                onClick={() => openModal(TileId.GEOGRAPHY, GeographyTab.COUNTRIES)}
                            />
                        </div>
                        <p className="text-sm text-muted mb-2">Geographic distribution of visitors</p>
                        {countriesQuery && (
                            <div className="overflow-x-auto">
                                <WebQuery
                                    query={countriesQuery}
                                    showIntervalSelect={false}
                                    tileId={TileId.GEOGRAPHY}
                                    insightProps={createInsightProps(TileId.GEOGRAPHY, GeographyTab.COUNTRIES)}
                                />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}

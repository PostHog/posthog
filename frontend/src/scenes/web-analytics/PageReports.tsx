import { IconExpand45 } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { InsightLogicProps } from '~/types'

import { WebQuery } from './tiles/WebAnalyticsTile'
import {
    PathTab,
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

    // Find the paths tile
    const pathsTile = tiles.find((tile) => tile.tileId === TileId.PATHS) as TabsTile | undefined

    // Get the queries for each tab
    const entryPathsQuery = pathsTile?.tabs.find((tab) => tab.id === PathTab.INITIAL_PATH)?.query
    const exitPathsQuery = pathsTile?.tabs.find((tab) => tab.id === PathTab.END_PATH)?.query
    const outboundClicksQuery = pathsTile?.tabs.find((tab) => tab.id === PathTab.EXIT_CLICK)?.query

    // Create insight props for the queries
    const createInsightProps = (tileId: TileId, tabId?: string): InsightLogicProps => ({
        dashboardItemId: `new-${tileId}${tabId ? `-${tabId}` : ''}`,
        loadPriority: 0,
        dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    })

    return (
        <div className="space-y-4 mt-4">
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
        </div>
    )
}

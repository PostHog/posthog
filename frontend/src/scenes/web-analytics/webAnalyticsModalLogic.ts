import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { TileId, WEB_ANALYTICS_DATA_COLLECTION_NODE_ID, WebAnalyticsTile } from './common'
import { getDashboardItemId, getNewInsightUrlFactory } from './insightsUtils'
import { pageReportsLogic } from './pageReportsLogic'
import { webAnalyticsLogic } from './webAnalyticsLogic'
import type { webAnalyticsModalLogicType } from './webAnalyticsModalLogicType'

export interface WebAnalyticsModalQuery {
    tileId: TileId
    tabId?: string
    title?: string | JSX.Element
    query: QuerySchema
    insightProps: InsightLogicProps
    showIntervalSelect?: boolean
    control?: JSX.Element
    canOpenInsight?: boolean
}

/**
 * This logic serves as a bridge between webAnalyticsLogic and pageReportsLogic
 * It combines tiles from both logics and provides a unified API for the modal
 */
export const webAnalyticsModalLogic = kea<webAnalyticsModalLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsModalLogic']),

    connect(() => ({
        values: [webAnalyticsLogic, ['tiles as webAnalyticsTiles'], pageReportsLogic, ['tiles as pageReportsTiles']],
    })),

    actions({
        openModal: (tileId: TileId, tabId?: string) => ({ tileId, tabId }),
        closeModal: () => true,
    }),

    reducers({
        modalTileAndTab: [
            null as { tileId: TileId; tabId?: string } | null,
            {
                openModal: (_, { tileId, tabId }) => ({
                    tileId,
                    tabId,
                }),
                closeModal: () => null,
            },
        ],
    }),

    selectors({
        // Combine tiles from both webAnalyticsLogic and flattened pageReportsLogic section tiles.
        combinedTiles: [
            (s) => [s.webAnalyticsTiles, s.pageReportsTiles],
            (webAnalyticsTiles: WebAnalyticsTile[], pageReportsTiles: WebAnalyticsTile[]): WebAnalyticsTile[] => {
                const flattenedPageReportsTiles = pageReportsTiles.flatMap((tile) => {
                    if (tile.kind === 'section' && tile.tiles) {
                        return [tile, ...tile.tiles]
                    }
                    return tile
                })

                return [...webAnalyticsTiles, ...flattenedPageReportsTiles]
            },
        ],

        modal: [
            (s) => [s.combinedTiles, s.modalTileAndTab],
            (
                tiles: WebAnalyticsTile[],
                modalTileAndTab: { tileId: TileId; tabId?: string } | null
            ): WebAnalyticsModalQuery | null => {
                if (!modalTileAndTab) {
                    return null
                }

                const { tileId, tabId } = modalTileAndTab
                const tile = tiles.find((t: WebAnalyticsTile) => t.tileId === tileId)

                if (!tile) {
                    return null
                }

                const extendQuery = (query: QuerySchema): QuerySchema => {
                    if (
                        query.kind === NodeKind.DataTableNode &&
                        (query.source.kind === NodeKind.WebStatsTableQuery ||
                            query.source.kind === NodeKind.WebExternalClicksTableQuery ||
                            query.source.kind === NodeKind.WebGoalsQuery)
                    ) {
                        return {
                            ...query,
                            source: {
                                ...query.source,
                                limit: 50,
                            },
                        }
                    }
                    return query
                }

                if (tile.kind === 'tabs') {
                    const tab = tile.tabs.find((t) => t.id === tabId)
                    if (!tab) {
                        return null
                    }

                    return {
                        tileId,
                        tabId,
                        title: tab.title,
                        showIntervalSelect: tab.showIntervalSelect,
                        control: tab.control,
                        insightProps: {
                            dashboardItemId: getDashboardItemId(tileId, tabId, true),
                            loadPriority: 0,
                            doNotLoad: false,
                            dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                        },
                        query: extendQuery(tab.query),
                        canOpenInsight: tab.canOpenInsight,
                    }
                } else if (tile.kind === 'query') {
                    return {
                        tileId,
                        title: tile.title,
                        showIntervalSelect: tile.showIntervalSelect,
                        control: tile.control,
                        insightProps: {
                            dashboardItemId: getDashboardItemId(tileId, undefined, true),
                            loadPriority: 0,
                            dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                        },
                        query: extendQuery(tile.query),
                        canOpenInsight: !!tile.canOpenInsight,
                    }
                }

                return null
            },
        ],

        getNewInsightUrl: [(s) => [s.combinedTiles], (tiles: WebAnalyticsTile[]) => getNewInsightUrlFactory(tiles)],
    }),
])

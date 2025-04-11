import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { urls } from 'scenes/urls'

import { NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { pageReportsLogic } from './pageReportsLogic'
import { TileId, WEB_ANALYTICS_DATA_COLLECTION_NODE_ID, webAnalyticsLogic, WebAnalyticsTile } from './webAnalyticsLogic'
import type { webAnalyticsModalLogicType } from './webAnalyticsModalLogicType'

interface WebAnalyticsModalQuery {
    tileId: TileId
    tabId?: string
    title?: string | JSX.Element
    query: QuerySchema
    insightProps: InsightLogicProps
    showIntervalSelect?: boolean
    control?: JSX.Element
    canOpenInsight?: boolean
}

// Utility to generate dashboard item IDs for the modal
const getDashboardItemId = (section: TileId, tab: string | undefined, isModal?: boolean): `new-${string}` => {
    return `new-AdHoc.web-analytics.${section}.${tab || 'default'}.${isModal ? 'modal' : 'default'}`
}

export type WebAnalyticsModalLogicType = {
    actions: {
        openModal: (tileId: TileId, tabId?: string) => { tileId: TileId; tabId?: string }
        closeModal: () => boolean
    }
    values: {
        combinedTiles: WebAnalyticsTile[]
        modal: WebAnalyticsModalQuery | null
        modalTileAndTab: { tileId: TileId; tabId?: string } | null
        getNewInsightUrl: (tileId: TileId, tabId?: string) => string | undefined
    }
    selectors: {
        combinedTiles: (state: any) => WebAnalyticsTile[]
        modal: (state: any) => WebAnalyticsModalQuery | null
        modalTileAndTab: (state: any) => { tileId: TileId; tabId?: string } | null
        getNewInsightUrl: (state: any) => (tileId: TileId, tabId?: string) => string | undefined
    }
}

/**
 * This logic serves as a bridge between webAnalyticsLogic and pageReportsLogic
 * It combines tiles from both logics and provides a unified API for the modal
 */
export const webAnalyticsModalLogic = kea<webAnalyticsModalLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsModalLogic']),

    connect({
        values: [webAnalyticsLogic, ['tiles as webAnalyticsTiles'], pageReportsLogic, ['tiles as pageReportsTiles']],
    }),

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
        // Combine tiles from both webAnalyticsLogic and pageReportsLogic
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

        // Build the modal data from the combined tiles
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
                    const tab = tile.tabs.find((t: any) => t.id === tabId)
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

        // Helper to get a URL for opening a tile as a new insight
        getNewInsightUrl: [
            (s) => [s.combinedTiles],
            (tiles: WebAnalyticsTile[]) => {
                return function getNewInsightUrl(tileId: TileId, tabId?: string): string | undefined {
                    const formatQueryForNewInsight = (query: QuerySchema): QuerySchema => {
                        if (query.kind === NodeKind.InsightVizNode) {
                            return {
                                ...query,
                                embedded: undefined,
                                hidePersonsModal: undefined,
                            }
                        }
                        return query
                    }

                    const tile = tiles.find((t: any) => t.tileId === tileId)
                    if (!tile) {
                        return undefined
                    }

                    if (tile.kind === 'tabs') {
                        const tab = tile.tabs.find((t: any) => t.id === tabId)
                        if (!tab) {
                            return undefined
                        }
                        return urls.insightNew({ query: formatQueryForNewInsight(tab.query) })
                    } else if (tile.kind === 'query') {
                        return urls.insightNew({ query: formatQueryForNewInsight(tile.query) })
                    } else if (tile.kind === 'section' && 'tiles' in tile) {
                        // For section tiles, find the first query tile inside
                        const queryTiles = tile.tiles.filter((t: any) => t.kind === 'query')
                        if (queryTiles.length > 0 && queryTiles[0].kind === 'query') {
                            return urls.insightNew({ query: formatQueryForNewInsight(queryTiles[0].query) })
                        }
                    } else if (tile.kind === 'replay') {
                        return urls.replay()
                    }

                    return undefined
                }
            },
        ],
    }),
])

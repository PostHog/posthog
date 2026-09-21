import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import { isWebAnalyticsInsightQuery } from '~/queries/utils'

import { TileId, WebAnalyticsTile } from './common'

export const getDashboardItemId = (section: TileId, tab: string | undefined, isModal?: boolean): `new-${string}` => {
    return `new-AdHoc.web-analytics.${section}.${tab || 'default'}.${isModal ? 'modal' : 'default'}`
}

export interface WebTileInsightSource {
    query: QuerySchema
    /** Undefined when the tile renders its title as a node rather than as text. */
    title?: string
}

const formatQueryForNewInsight = (query: QuerySchema): QuerySchema => {
    if (query.kind === NodeKind.InsightVizNode) {
        return {
            ...query,
            embedded: undefined,
            hidePersonsModal: undefined,
        }
    }
    // Extract source from DataTableNode if present
    if (query.kind === NodeKind.DataTableNode && 'source' in query) {
        const source = query.source
        if (isWebAnalyticsInsightQuery(source)) {
            return {
                kind: NodeKind.InsightVizNode,
                source: source,
            } as InsightVizNode
        }
        return source
    }
    // Wrap Web Analytics queries in InsightVizNode so they can be used as insights
    if (isWebAnalyticsInsightQuery(query)) {
        return {
            kind: NodeKind.InsightVizNode,
            source: query,
        } as InsightVizNode
    }
    return query
}

/** The insight query and name a tile carries, shared by "Open as insight" and "Add to dashboard". */
export const getNewInsightSourceFactory = (tiles: WebAnalyticsTile[]) => {
    return function getNewInsightSource(tileId: TileId, tabId?: string): WebTileInsightSource | undefined {
        const tile = tiles.find((t) => t.tileId === tileId)
        if (!tile) {
            return undefined
        }

        if (tile.kind === 'tabs') {
            const tab = tile.tabs.find((t) => t.id === tabId)
            if (!tab) {
                return undefined
            }
            return {
                query: formatQueryForNewInsight(tab.query),
                title: typeof tab.title === 'string' ? tab.title : undefined,
            }
        } else if (tile.kind === 'query') {
            return { query: formatQueryForNewInsight(tile.query), title: tile.title }
        } else if (tile.kind === 'section' && 'tiles' in tile) {
            // For section tiles, find the first query tile inside
            const queryTile = tile.tiles.find((t) => t.kind === 'query')
            if (queryTile?.kind === 'query') {
                return { query: formatQueryForNewInsight(queryTile.query), title: queryTile.title ?? tile.title }
            }
        }

        return undefined
    }
}

export const getNewInsightUrlFactory = (tiles: WebAnalyticsTile[]) => {
    const getNewInsightSource = getNewInsightSourceFactory(tiles)

    return function getNewInsightUrl(tileId: TileId, tabId?: string): string | undefined {
        if (tiles.find((t) => t.tileId === tileId)?.kind === 'replay') {
            return urls.replay()
        }

        const source = getNewInsightSource(tileId, tabId)
        return source ? urls.insightNew({ query: source.query, sceneSource: 'web-analytics' }) : undefined
    }
}

/** Names the saved insight after the tile, so it is recognizable in the insight list. */
export const webTileInsightName = (title: string | undefined): string =>
    title ? `Web analytics: ${title}` : 'Web analytics tile'

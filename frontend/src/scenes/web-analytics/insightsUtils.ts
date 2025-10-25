import { urls } from 'scenes/urls'

import { NodeKind, QuerySchema } from '~/queries/schema/schema-general'

import { TileId, WebAnalyticsTile } from './common'

export const getDashboardItemId = (section: TileId, tab: string | undefined, isModal?: boolean): `new-${string}` => {
    return `new-AdHoc.web-analytics.${section}.${tab || 'default'}.${isModal ? 'modal' : 'default'}`
}

export const getNewInsightUrlFactory = (tiles: WebAnalyticsTile[]) => {
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

        const tile = tiles.find((t) => t.tileId === tileId)
        if (!tile) {
            return undefined
        }

        if (tile.kind === 'tabs') {
            const tab = tile.tabs.find((t) => t.id === tabId)
            if (!tab) {
                return undefined
            }
            return urls.insightNew({ query: formatQueryForNewInsight(tab.query), sceneSource: 'web-analytics' })
        } else if (tile.kind === 'query') {
            return urls.insightNew({ query: formatQueryForNewInsight(tile.query), sceneSource: 'web-analytics' })
        } else if (tile.kind === 'section' && 'tiles' in tile) {
            // For section tiles, find the first query tile inside
            const queryTiles = tile.tiles.filter((t: any) => t.kind === 'query')
            if (queryTiles.length > 0 && queryTiles[0].kind === 'query') {
                return urls.insightNew({
                    query: formatQueryForNewInsight(queryTiles[0].query),
                    sceneSource: 'web-analytics',
                })
            }
        } else if (tile.kind === 'replay') {
            return urls.replay()
        }

        return undefined
    }
}

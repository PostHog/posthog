import { TileId } from 'scenes/web-analytics/common'

import { WebAnalyticsConcern } from './types'

const CONCERN_TILES: Record<WebAnalyticsConcern, TileId[]> = {
    [WebAnalyticsConcern.TRAFFIC]: [TileId.OVERVIEW, TileId.GRAPHS],
    [WebAnalyticsConcern.SOURCES]: [TileId.SOURCES],
    [WebAnalyticsConcern.PATHS]: [TileId.PATHS],
    [WebAnalyticsConcern.GEOGRAPHY]: [TileId.GEOGRAPHY],
    [WebAnalyticsConcern.DEVICES]: [TileId.DEVICES],
    [WebAnalyticsConcern.RETENTION]: [TileId.RETENTION],
    [WebAnalyticsConcern.GOALS_CONVERSIONS]: [TileId.GOALS],
    [WebAnalyticsConcern.ENGAGEMENT]: [TileId.ACTIVE_HOURS, TileId.REPLAY],
    [WebAnalyticsConcern.ERRORS]: [TileId.ERROR_TRACKING, TileId.FRUSTRATING_PAGES],
}

export const FOCUS_MODE_TILE_IDS: TileId[] = [
    TileId.OVERVIEW,
    TileId.GRAPHS,
    TileId.PATHS,
    TileId.SOURCES,
    TileId.DEVICES,
    TileId.GEOGRAPHY,
    TileId.ACTIVE_HOURS,
    TileId.RETENTION,
    TileId.GOALS,
    TileId.REPLAY,
    TileId.ERROR_TRACKING,
    TileId.FRUSTRATING_PAGES,
]

export const getTilesForFocusConcerns = (concerns: WebAnalyticsConcern[]): Set<TileId> => {
    const tiles = new Set<TileId>([TileId.OVERVIEW])
    for (const concern of concerns) {
        for (const tileId of CONCERN_TILES[concern]) {
            tiles.add(tileId)
        }
    }
    return tiles
}

export const getHiddenTilesForFocusConcerns = (concerns: WebAnalyticsConcern[]): TileId[] => {
    const visibleTiles = getTilesForFocusConcerns(concerns)
    return FOCUS_MODE_TILE_IDS.filter((tileId) => !visibleTiles.has(tileId))
}

export const computeFocusHiddenTiles = (currentHiddenTiles: TileId[], concerns: WebAnalyticsConcern[]): TileId[] => {
    const focusModeTileSet = new Set<TileId>(FOCUS_MODE_TILE_IDS)
    const nonFocusHiddenTiles = currentHiddenTiles.filter((tileId) => !focusModeTileSet.has(tileId))
    const focusHiddenTiles = getHiddenTilesForFocusConcerns(concerns)
    return [...nonFocusHiddenTiles, ...focusHiddenTiles]
}

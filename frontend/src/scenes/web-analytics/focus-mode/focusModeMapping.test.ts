import { TileId } from 'scenes/web-analytics/common'

import { FOCUS_MODE_TILE_IDS, getHiddenTilesForFocusConcerns, getTilesForFocusConcerns } from './focusModeMapping'
import { WebAnalyticsConcern } from './types'

describe('getTilesForFocusConcerns', () => {
    it('always includes OVERVIEW as the headline tile', () => {
        expect(getTilesForFocusConcerns([])).toContain(TileId.OVERVIEW)
    })

    it('maps traffic concern to OVERVIEW and GRAPHS', () => {
        const result = getTilesForFocusConcerns([WebAnalyticsConcern.TRAFFIC])
        expect(result).toEqual(new Set([TileId.OVERVIEW, TileId.GRAPHS]))
    })

    it('maps engagement concern to ACTIVE_HOURS and REPLAY', () => {
        const result = getTilesForFocusConcerns([WebAnalyticsConcern.ENGAGEMENT])
        expect(result).toEqual(new Set([TileId.OVERVIEW, TileId.ACTIVE_HOURS, TileId.REPLAY]))
    })

    it('maps errors concern to ERROR_TRACKING and FRUSTRATING_PAGES', () => {
        const result = getTilesForFocusConcerns([WebAnalyticsConcern.ERRORS])
        expect(result).toEqual(new Set([TileId.OVERVIEW, TileId.ERROR_TRACKING, TileId.FRUSTRATING_PAGES]))
    })

    it('unions multiple concerns without duplicates', () => {
        const result = getTilesForFocusConcerns([
            WebAnalyticsConcern.TRAFFIC,
            WebAnalyticsConcern.SOURCES,
            WebAnalyticsConcern.PATHS,
        ])
        expect(result).toEqual(new Set([TileId.OVERVIEW, TileId.GRAPHS, TileId.SOURCES, TileId.PATHS]))
    })

    it('returns hidden focus tiles for the selected concerns', () => {
        expect(getHiddenTilesForFocusConcerns([WebAnalyticsConcern.RETENTION])).toEqual(
            FOCUS_MODE_TILE_IDS.filter((tileId) => ![TileId.OVERVIEW, TileId.RETENTION].includes(tileId))
        )
    })

    it('lists the analytics tiles focus mode can hide', () => {
        expect(FOCUS_MODE_TILE_IDS).toEqual([
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
        ])
    })
})

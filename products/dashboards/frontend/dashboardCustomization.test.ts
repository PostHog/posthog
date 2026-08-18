import type { Layout } from 'react-grid-layout'

import {
    freePlacementCompactor,
    makeRoomInRowCompactor,
    resolveFreePlacementCollisions,
    restoreUnmovedTilePositions,
} from './dashboardCustomization'

const geometry = (layout: Layout): Layout => layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))

describe('dashboard grid compactors', () => {
    it('preserves tile coordinates without returning the original layout items', () => {
        const layout = [
            { i: 'first', x: 4, y: 3, w: 4, h: 3 },
            { i: 'second', x: 0, y: 8, w: 6, h: 4 },
        ] as Layout

        const compactedLayout = freePlacementCompactor.compact(layout, 12)

        expect(geometry(compactedLayout)).toEqual(layout)
        expect(compactedLayout[0]).not.toBe(layout[0])
        expect(compactedLayout[1]).not.toBe(layout[1])
    })

    it('keeps an unrelated tile in its row when making room in a row', () => {
        const layout = [
            { i: 'first', x: 0, y: 0, w: 4, h: 3 },
            { i: 'second', x: 8, y: 5, w: 4, h: 3 },
        ] as Layout

        expect(geometry(makeRoomInRowCompactor.compact(layout, 12))).toEqual([
            { i: 'first', x: 0, y: 0, w: 4, h: 3 },
            { i: 'second', x: 0, y: 5, w: 4, h: 3 },
        ])
    })

    it('moves a conflicting tile right when it fits', () => {
        const layout = [
            { i: 'first', x: 0, y: 0, w: 4, h: 3 },
            { i: 'second', x: 2, y: 0, w: 4, h: 3 },
        ] as Layout

        expect(geometry(makeRoomInRowCompactor.compact(layout, 12))).toEqual([
            { i: 'first', x: 0, y: 0, w: 4, h: 3 },
            { i: 'second', x: 4, y: 0, w: 4, h: 3 },
        ])
    })

    it('moves an overflowing row item directly below the row', () => {
        const layout = [
            { i: 'first', x: 0, y: 0, w: 10, h: 3 },
            { i: 'second', x: 10, y: 0, w: 4, h: 3 },
            { i: 'third', x: 6, y: 6, w: 4, h: 3 },
        ] as Layout

        expect(geometry(makeRoomInRowCompactor.compact(layout, 12))).toEqual([
            { i: 'first', x: 0, y: 0, w: 10, h: 3 },
            { i: 'second', x: 0, y: 3, w: 4, h: 3 },
            { i: 'third', x: 0, y: 6, w: 4, h: 3 },
        ])
    })

    it('restores a displaced tile after the active tile moves away', () => {
        const baseline = [
            { i: 'active', x: 0, y: 0, w: 6, h: 4 },
            { i: 'displaced', x: 6, y: 0, w: 6, h: 4 },
        ] as Layout
        const layout = [
            { i: 'active', x: 0, y: 4, w: 6, h: 4 },
            { i: 'displaced', x: 0, y: 8, w: 6, h: 4 },
        ] as Layout

        expect(geometry(restoreUnmovedTilePositions(layout, baseline, 'active'))).toEqual([
            { i: 'active', x: 0, y: 4, w: 6, h: 4 },
            { i: 'displaced', x: 6, y: 0, w: 6, h: 4 },
        ])
    })

    it('restores the original layout when a drag returns to its starting position', () => {
        const baseline = [
            { i: 'active', x: 0, y: 0, w: 6, h: 4 },
            { i: 'displaced', x: 6, y: 0, w: 6, h: 4 },
        ] as Layout
        const layout = [
            { i: 'active', x: 0, y: 0, w: 6, h: 4 },
            { i: 'displaced', x: 6, y: 4, w: 6, h: 4 },
        ] as Layout

        expect(geometry(restoreUnmovedTilePositions(layout, baseline, 'active'))).toEqual(baseline)
    })

    it('resolves a collision chain after restoring tile positions', () => {
        const baseline = [
            { i: 'active', x: 0, y: 0, w: 6, h: 4 },
            { i: 'neighbor', x: 0, y: 4, w: 6, h: 4 },
            { i: 'next-neighbor', x: 0, y: 8, w: 6, h: 4 },
        ] as Layout
        const layout = [
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
            { i: 'neighbor', x: 0, y: 8, w: 6, h: 4 },
            { i: 'next-neighbor', x: 0, y: 12, w: 6, h: 4 },
        ] as Layout

        const restoredLayout = restoreUnmovedTilePositions(layout, baseline, 'active')

        expect(geometry(resolveFreePlacementCollisions(restoredLayout, 12, 'active'))).toEqual([
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
            { i: 'neighbor', x: 0, y: 8, w: 6, h: 4 },
            { i: 'next-neighbor', x: 0, y: 12, w: 6, h: 4 },
        ])
    })
})

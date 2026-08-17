import type { Layout } from 'react-grid-layout'

import { makeRoomInRowCompactor, preservePositionsCompactor } from './dashboardCustomization'

const geometry = (layout: Layout): Layout => layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))

describe('dashboard grid compactors', () => {
    it('prevents a drag from moving other tiles', () => {
        expect(preservePositionsCompactor.preventCollision).toBe(true)
    })

    it('preserves tile coordinates without returning the original layout items', () => {
        const layout = [
            { i: 'first', x: 4, y: 3, w: 4, h: 3 },
            { i: 'second', x: 0, y: 8, w: 6, h: 4 },
        ] as Layout

        const compactedLayout = preservePositionsCompactor.compact(layout, 12)

        expect(geometry(compactedLayout)).toEqual(layout)
        expect(compactedLayout[0]).not.toBe(layout[0])
        expect(compactedLayout[1]).not.toBe(layout[1])
    })

    it('moves only tiles that overlap', () => {
        const layout = [
            { i: 'first', x: 0, y: 0, w: 6, h: 4 },
            { i: 'second', x: 0, y: 2, w: 6, h: 4 },
            { i: 'third', x: 6, y: 2, w: 6, h: 4 },
        ] as Layout

        const compactedLayout = preservePositionsCompactor.compact(layout, 12)

        expect(geometry(compactedLayout)).toEqual([
            { i: 'first', x: 0, y: 0, w: 6, h: 4 },
            { i: 'second', x: 0, y: 4, w: 6, h: 4 },
            { i: 'third', x: 6, y: 2, w: 6, h: 4 },
        ])
    })

    it('preserves non-conflicting coordinates when making room in a row', () => {
        const layout = [
            { i: 'first', x: 0, y: 0, w: 4, h: 3 },
            { i: 'second', x: 8, y: 5, w: 4, h: 3 },
        ] as Layout

        expect(geometry(makeRoomInRowCompactor.compact(layout, 12))).toEqual(layout)
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
            { i: 'third', x: 6, y: 6, w: 4, h: 3 },
        ])
    })
})

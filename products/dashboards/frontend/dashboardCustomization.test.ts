import type { Layout } from 'react-grid-layout'

import { resolveFreePlacementCollisions } from './dashboardCustomization'

const geometry = (layout: Layout): Layout => layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))

describe('dashboard grid compactors', () => {
    it('moves a collision chain below the active tile', () => {
        const layout = [
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
            { i: 'side-tile', x: 6, y: 3, w: 6, h: 1 },
            { i: 'neighbor', x: 0, y: 4, w: 6, h: 4 },
            { i: 'next-neighbor', x: 0, y: 8, w: 6, h: 4 },
        ] as Layout

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual([
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
            { i: 'side-tile', x: 6, y: 5, w: 6, h: 1 },
            { i: 'neighbor', x: 0, y: 6, w: 6, h: 4 },
            { i: 'next-neighbor', x: 0, y: 10, w: 6, h: 4 },
        ])
    })

    it('moves entire sections down together when a tile is dragged into an occupied row', () => {
        const layout = [
            { i: 'heading-one', x: 0, y: 0, w: 12, h: 1 },
            { i: 'one-left', x: 0, y: 1, w: 6, h: 3 },
            { i: 'one-right', x: 6, y: 1, w: 6, h: 3 },
            { i: 'heading-two', x: 0, y: 4, w: 12, h: 1 },
            { i: 'active', x: 0, y: 1, w: 6, h: 3 },
            { i: 'two-right', x: 6, y: 5, w: 6, h: 3 },
            { i: 'heading-three', x: 0, y: 8, w: 12, h: 1 },
            { i: 'three-left', x: 0, y: 9, w: 6, h: 3 },
            { i: 'three-right', x: 6, y: 9, w: 6, h: 3 },
        ] as Layout

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual([
            { i: 'heading-one', x: 0, y: 0, w: 12, h: 1 },
            { i: 'one-left', x: 0, y: 4, w: 6, h: 3 },
            { i: 'one-right', x: 6, y: 4, w: 6, h: 3 },
            { i: 'heading-two', x: 0, y: 7, w: 12, h: 1 },
            { i: 'active', x: 0, y: 1, w: 6, h: 3 },
            { i: 'two-right', x: 6, y: 8, w: 6, h: 3 },
            { i: 'heading-three', x: 0, y: 11, w: 12, h: 1 },
            { i: 'three-left', x: 0, y: 12, w: 6, h: 3 },
            { i: 'three-right', x: 6, y: 12, w: 6, h: 3 },
        ])
    })

    it('leaves other tiles in place when the drop is in empty space', () => {
        const layout = [
            { i: 'heading', x: 0, y: 0, w: 12, h: 1 },
            { i: 'neighbor', x: 0, y: 1, w: 6, h: 3 },
            { i: 'active', x: 6, y: 1, w: 6, h: 3 },
            { i: 'next-heading', x: 0, y: 5, w: 12, h: 1 },
        ] as Layout

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual(geometry(layout))
    })

    it('bounds malformed tile heights before resolving collisions', () => {
        const layout = [
            { i: 'active', x: 0, y: 0, w: 6, h: 1_000_000 },
            { i: 'neighbor', x: 0, y: 5, w: 6, h: 4 },
        ] as Layout

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual([
            { i: 'active', x: 0, y: 0, w: 6, h: 100 },
            { i: 'neighbor', x: 0, y: 100, w: 6, h: 4 },
        ])
    })
})

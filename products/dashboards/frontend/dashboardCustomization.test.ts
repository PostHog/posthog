import type { Layout } from 'react-grid-layout'

import {
    DashboardGridCompaction,
    getDashboardGridCompactor,
    resolveFreePlacementCollisions,
} from './dashboardCustomization'

const geometry = (layout: Layout): Layout => layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))

const resolveVerticalDragCollisions = (layout: Layout, cols: number, activeTileId: string): Layout =>
    getDashboardGridCompactor(DashboardGridCompaction.Vertical).compactInteraction(
        cols,
        activeTileId,
        'drag',
        layout,
        layout
    )

describe('dashboard grid compactors', () => {
    it('moves a collision chain below the active tile', () => {
        const layout = [
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
            { i: 'neighbor', x: 0, y: 4, w: 6, h: 4 },
            { i: 'next-neighbor', x: 0, y: 8, w: 6, h: 4 },
        ] as Layout

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual([
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
            { i: 'neighbor', x: 0, y: 6, w: 6, h: 4 },
            { i: 'next-neighbor', x: 0, y: 10, w: 6, h: 4 },
        ])
    })

    // Both resolvers walk the occupancy grid one row at a time on every pointer frame, so an unbounded
    // height freezes the tab on either path.
    it.each([
        ['free-form placement', resolveFreePlacementCollisions],
        ['a vertical drag', resolveVerticalDragCollisions],
    ])('bounds malformed tile heights before resolving collisions with %s', (_, resolveCollisions) => {
        const layout = [
            { i: 'active', x: 0, y: 0, w: 6, h: 1_000_000 },
            { i: 'neighbor', x: 0, y: 5, w: 6, h: 4 },
        ] as Layout

        expect(geometry(resolveCollisions(layout, 12, 'active'))).toEqual([
            { i: 'active', x: 0, y: 0, w: 6, h: 100 },
            { i: 'neighbor', x: 0, y: 100, w: 6, h: 4 },
        ])
    })
})

import { moveElement } from 'react-grid-layout'
import type { Layout, LayoutItem } from 'react-grid-layout'

import {
    DashboardGridCompaction,
    getDashboardGridCompactor,
    resolveFreePlacementCollisions,
} from './dashboardCustomization'

const geometry = (layout: Layout): Layout => layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))

describe('dashboard grid compactors', () => {
    it('keeps a dragged image at the intended row instead of moving it below a chart', () => {
        const image: LayoutItem = { i: 'image', x: 0, y: 12, w: 6, h: 4 }
        const layout: Layout = [
            { i: 'chart', x: 0, y: 4, w: 6, h: 4 },
            { i: 'side-chart', x: 6, y: 4, w: 6, h: 4 },
            { i: 'next-chart', x: 0, y: 8, w: 6, h: 4 },
            image,
        ]
        const compactor = getDashboardGridCompactor(DashboardGridCompaction.Stable)
        const moved = moveElement(layout, image, 0, 2, true, false, compactor.type, 12, compactor.allowOverlap)

        expect(geometry(compactor.compactInteraction(12, image.i, moved, moved))).toEqual([
            { i: 'chart', x: 0, y: 6, w: 6, h: 4 },
            { i: 'side-chart', x: 6, y: 4, w: 6, h: 4 },
            { i: 'next-chart', x: 0, y: 10, w: 6, h: 4 },
            { i: 'image', x: 0, y: 2, w: 6, h: 4 },
        ])
    })

    it('leaves the image beside a displaced insight in place', () => {
        const layout: Layout = [
            { i: 'top-left', x: 0, y: 0, w: 6, h: 3 },
            { i: 'top-right', x: 6, y: 0, w: 6, h: 3 },
            { i: 'image', x: 0, y: 3, w: 6, h: 3 },
            { i: 'retention', x: 6, y: 3, w: 6, h: 3 },
            { i: 'active', x: 6, y: 3, w: 6, h: 3 },
        ]

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual([
            { i: 'top-left', x: 0, y: 0, w: 6, h: 3 },
            { i: 'top-right', x: 6, y: 0, w: 6, h: 3 },
            { i: 'image', x: 0, y: 3, w: 6, h: 3 },
            { i: 'retention', x: 6, y: 6, w: 6, h: 3 },
            { i: 'active', x: 6, y: 3, w: 6, h: 3 },
        ])
    })

    it('moves a collision chain below the active tile', () => {
        const layout = [
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
            { i: 'side-tile', x: 6, y: 3, w: 6, h: 1 },
            { i: 'neighbor', x: 0, y: 4, w: 6, h: 4 },
            { i: 'next-neighbor', x: 0, y: 8, w: 6, h: 4 },
        ] as Layout

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual([
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
            { i: 'side-tile', x: 6, y: 3, w: 6, h: 1 },
            { i: 'neighbor', x: 0, y: 6, w: 6, h: 4 },
            { i: 'next-neighbor', x: 0, y: 10, w: 6, h: 4 },
        ])
    })

    it.each([1, 2, 3])('keeps three sections in order when a tile is dropped at row %i', (dropRow) => {
        const shift = dropRow + 2
        const layout = [
            { i: 'heading-one', x: 0, y: 0, w: 12, h: 1 },
            { i: 'heading-two', x: 0, y: 4, w: 12, h: 1 },
            { i: 'one-left', x: 0, y: 1, w: 6, h: 3 },
            { i: 'one-right', x: 6, y: 1, w: 6, h: 3 },
            { i: 'active', x: 0, y: dropRow, w: 6, h: 3 },
            { i: 'two-left', x: 0, y: 5, w: 6, h: 3 },
            { i: 'two-right', x: 6, y: 5, w: 6, h: 3 },
            { i: 'heading-three', x: 0, y: 8, w: 12, h: 1 },
            { i: 'three-left', x: 0, y: 9, w: 6, h: 3 },
        ] as Layout

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual([
            { i: 'heading-one', x: 0, y: 0, w: 12, h: 1 },
            { i: 'heading-two', x: 0, y: 4 + shift, w: 12, h: 1 },
            { i: 'one-left', x: 0, y: 1 + shift, w: 6, h: 3 },
            { i: 'one-right', x: 6, y: 1, w: 6, h: 3 },
            { i: 'active', x: 0, y: dropRow, w: 6, h: 3 },
            { i: 'two-left', x: 0, y: 5 + shift, w: 6, h: 3 },
            { i: 'two-right', x: 6, y: 5 + shift, w: 6, h: 3 },
            { i: 'heading-three', x: 0, y: 8 + shift, w: 12, h: 1 },
            { i: 'three-left', x: 0, y: 9 + shift, w: 6, h: 3 },
        ])
    })

    it('pushes a tall tile below the drop without moving its side neighbor', () => {
        const layout: Layout = [
            { i: 'heading', x: 0, y: 0, w: 12, h: 1 },
            { i: 'tall', x: 0, y: 1, w: 6, h: 6 },
            { i: 'side-tile', x: 6, y: 1, w: 6, h: 3 },
            { i: 'active', x: 0, y: 4, w: 6, h: 3 },
            { i: 'next-heading', x: 0, y: 7, w: 12, h: 1 },
            { i: 'next-tile', x: 0, y: 8, w: 6, h: 3 },
        ]

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual([
            { i: 'heading', x: 0, y: 0, w: 12, h: 1 },
            { i: 'tall', x: 0, y: 7, w: 6, h: 6 },
            { i: 'side-tile', x: 6, y: 1, w: 6, h: 3 },
            { i: 'active', x: 0, y: 4, w: 6, h: 3 },
            { i: 'next-heading', x: 0, y: 13, w: 12, h: 1 },
            { i: 'next-tile', x: 0, y: 14, w: 6, h: 3 },
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

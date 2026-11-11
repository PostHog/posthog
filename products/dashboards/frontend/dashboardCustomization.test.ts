import { moveElement } from 'react-grid-layout'
import type { Layout, LayoutItem } from 'react-grid-layout'

import {
    DashboardGridCompaction,
    getDashboardGridCompactor,
    resolveFreePlacementCollisions,
} from './dashboardCustomization'

const geometry = (layout: Layout): Layout => layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))

describe('dashboard grid compactors', () => {
    it.each([
        { dropColumn: 4, dropRow: 0, rightStartRow: 0, imageColumn: 6, leftRow: 0, rightRow: 4 },
        { dropColumn: 3, dropRow: 0, rightStartRow: 0, imageColumn: 2, leftRow: 4, rightRow: 0 },
        { dropColumn: 4, imageColumn: 6, leftRow: 0, rightRow: 6, rightStartRow: 1, dropRow: 2 },
    ])(
        'inserts an image between adjacent charts near column $dropColumn at row $dropRow',
        ({ dropColumn, imageColumn, leftRow, rightRow, rightStartRow, dropRow }) => {
            const image: LayoutItem = { i: 'image', x: 0, y: 8, w: 4, h: 4 }
            const layout: Layout = [
                { i: 'left-chart', x: 0, y: 0, w: 6, h: 4 },
                { i: 'right-chart', x: 6, y: rightStartRow, w: 6, h: 4 },
                image,
            ]
            const compactor = getDashboardGridCompactor(DashboardGridCompaction.Stable)
            const moved = moveElement(
                layout,
                image,
                dropColumn,
                dropRow,
                true,
                false,
                compactor.type,
                12,
                compactor.allowOverlap
            )

            expect(geometry(compactor.compactInteraction(12, image.i, moved, moved))).toEqual([
                { i: 'left-chart', x: 0, y: leftRow, w: 6, h: 4 },
                { i: 'right-chart', x: 6, y: rightRow, w: 6, h: 4 },
                { i: 'image', x: imageColumn, y: dropRow, w: 4, h: 4 },
            ])
        }
    )

    it.each([
        { dropColumn: 4, imageColumn: 2, leftRow: 6, topRow: 0, bottomRow: 4 },
        { dropColumn: 5, imageColumn: 6, leftRow: 0, topRow: 6, bottomRow: 10 },
    ])(
        'snaps a seam drop beside stacked charts at column $dropColumn',
        ({ dropColumn, imageColumn, leftRow, topRow, bottomRow }) => {
            const layout: Layout = [
                { i: 'left', x: 0, y: 0, w: 6, h: 8 },
                { i: 'top', x: 6, y: 0, w: 6, h: 4 },
                { i: 'bottom', x: 6, y: 4, w: 6, h: 4 },
                { i: 'image', x: dropColumn, y: 2, w: 4, h: 4 },
            ]

            expect(geometry(resolveFreePlacementCollisions(layout, 12, 'image'))).toEqual([
                { i: 'left', x: 0, y: leftRow, w: 6, h: 8 },
                { i: 'top', x: 6, y: topRow, w: 6, h: 4 },
                { i: 'bottom', x: 6, y: bottomRow, w: 6, h: 4 },
                { i: 'image', x: imageColumn, y: 2, w: 4, h: 4 },
            ])
        }
    )

    it('keeps a resized tile in place when it grows across two charts', () => {
        const layout: Layout = [
            { i: 'left-chart', x: 0, y: 2, w: 6, h: 4 },
            { i: 'right-chart', x: 6, y: 2, w: 6, h: 4 },
            { i: 'image', x: 4, y: 0, w: 4, h: 4 },
        ]
        const compactor = getDashboardGridCompactor(DashboardGridCompaction.Stable)

        expect(geometry(compactor.compactInteraction(12, 'image', layout, layout, false))).toEqual([
            { i: 'left-chart', x: 0, y: 4, w: 6, h: 4 },
            { i: 'right-chart', x: 6, y: 4, w: 6, h: 4 },
            { i: 'image', x: 4, y: 0, w: 4, h: 4 },
        ])
    })

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
            { i: 'later-tile', x: 0, y: 20, w: 6, h: 4 },
        ] as Layout

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual([
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
            { i: 'side-tile', x: 6, y: 3, w: 6, h: 1 },
            { i: 'neighbor', x: 0, y: 6, w: 6, h: 4 },
            { i: 'next-neighbor', x: 0, y: 10, w: 6, h: 4 },
            { i: 'later-tile', x: 0, y: 20, w: 6, h: 4 },
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

    it('keeps tiles below a displaced heading when the section has a gap', () => {
        const layout: Layout = [
            { i: 'upper', x: 0, y: 1, w: 6, h: 4 },
            { i: 'next-heading', x: 0, y: 5, w: 12, h: 1 },
            { i: 'section-right', x: 6, y: 7, w: 6, h: 2 },
            { i: 'distant', x: 6, y: 25, w: 6, h: 2 },
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
        ]

        expect(geometry(resolveFreePlacementCollisions(layout, 12, 'active'))).toEqual([
            { i: 'upper', x: 0, y: 6, w: 6, h: 4 },
            { i: 'next-heading', x: 0, y: 10, w: 12, h: 1 },
            { i: 'section-right', x: 6, y: 12, w: 6, h: 2 },
            { i: 'distant', x: 6, y: 25, w: 6, h: 2 },
            { i: 'active', x: 0, y: 2, w: 6, h: 4 },
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

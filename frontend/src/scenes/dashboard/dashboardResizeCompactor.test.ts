import type { Layout } from 'react-grid-layout'

import { resizeNeighborToFitRow, restoreUnmovedItemPositions } from './dashboardResizeCompactor'

describe('dashboard resize compactor', () => {
    const baseline: Layout = [
        { i: 'active', x: 0, y: 0, w: 6, h: 4, minW: 2 },
        { i: 'neighbor', x: 6, y: 0, w: 6, h: 4, minW: 2 },
    ]

    it('restores a displaced tile when the active tile moves away', () => {
        const layout: Layout = [
            { i: 'active', x: 0, y: 4, w: 6, h: 4, minW: 2 },
            { i: 'neighbor', x: 6, y: 4, w: 6, h: 4, minW: 2 },
        ]

        expect(restoreUnmovedItemPositions(layout, baseline, 'active')).toEqual([
            { i: 'active', x: 0, y: 4, w: 6, h: 4, minW: 2 },
            { i: 'neighbor', x: 6, y: 0, w: 6, h: 4, minW: 2 },
        ])
    })

    test.each([
        {
            name: 'shrinks a neighbor that still meets its minimum width',
            activeWidth: 8,
            expectedNeighbor: { x: 8, y: 0, w: 4 },
        },
        {
            name: 'keeps the grid layout when the neighbor would be narrower than its minimum width',
            activeWidth: 11,
            expectedNeighbor: { x: 6, y: 4, w: 6 },
        },
    ])('$name', ({ activeWidth, expectedNeighbor }) => {
        const layout: Layout = [
            { i: 'active', x: 0, y: 0, w: activeWidth, h: 4, minW: 2 },
            { i: 'neighbor', x: 6, y: 4, w: 6, h: 4, minW: 2 },
        ]

        const neighbor = resizeNeighborToFitRow(layout, baseline, 'active').find((item) => item.i === 'neighbor')

        expect(neighbor).toMatchObject(expectedNeighbor)
    })

    it('shrinks the left neighbor when the active tile expands left', () => {
        const leftBaseline: Layout = [
            { i: 'neighbor', x: 0, y: 0, w: 6, h: 4, minW: 2 },
            { i: 'active', x: 6, y: 0, w: 6, h: 4, minW: 2 },
        ]
        const layout: Layout = [
            { i: 'neighbor', x: 0, y: 4, w: 6, h: 4, minW: 2 },
            { i: 'active', x: 4, y: 0, w: 8, h: 4, minW: 2 },
        ]

        const neighbor = resizeNeighborToFitRow(layout, leftBaseline, 'active').find((item) => item.i === 'neighbor')

        expect(neighbor).toMatchObject({ x: 0, y: 0, w: 4 })
    })
})

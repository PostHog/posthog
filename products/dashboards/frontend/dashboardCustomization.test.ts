import type { Layout } from 'react-grid-layout'

import { resolveFreePlacementCollisions, restoreUnmovedTilePositions } from './dashboardCustomization'

const geometry = (layout: Layout): Layout => layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))

describe('dashboard grid compactors', () => {
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
})

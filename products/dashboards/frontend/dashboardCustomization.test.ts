import type { Layout } from 'react-grid-layout'

import { resolveFreePlacementCollisions } from './dashboardCustomization'

const geometry = (layout: Layout): Layout => layout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))

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

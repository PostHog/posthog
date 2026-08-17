import type { Layout } from 'react-grid-layout'

import { preservePositionsCompactor } from './dashboardCustomization'

describe('preservePositionsCompactor', () => {
    it('preserves tile coordinates without returning the original layout items', () => {
        const layout = [
            { i: 'first', x: 4, y: 3, w: 4, h: 3 },
            { i: 'second', x: 0, y: 8, w: 6, h: 4 },
        ] as Layout

        const compactedLayout = preservePositionsCompactor.compact(layout, 12)

        expect(compactedLayout.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))).toEqual(layout)
        expect(compactedLayout[0]).not.toBe(layout[0])
        expect(compactedLayout[1]).not.toBe(layout[1])
    })
})

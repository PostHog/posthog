import { act, renderHook } from '@testing-library/react'
import { getLayoutItem, moveElement } from 'react-grid-layout'
import type { Layout } from 'react-grid-layout'

import { useDashboardLayoutInteraction } from 'scenes/dashboard/useDashboardLayoutInteraction'

import { DashboardGridCompaction } from 'products/dashboards/frontend/dashboardCustomization'

const COLS = 12

describe('useDashboardLayoutInteraction', () => {
    const baseline: Layout = [
        { i: 'left-top', x: 0, y: 0, w: 6, h: 4 },
        { i: 'right-top', x: 6, y: 0, w: 6, h: 4 },
        { i: 'left-middle', x: 0, y: 4, w: 6, h: 4 },
        { i: 'right-middle', x: 6, y: 4, w: 6, h: 4 },
        { i: 'left-bottom', x: 0, y: 8, w: 6, h: 4 },
        { i: 'right-bottom', x: 6, y: 8, w: 6, h: 4 },
        { i: 'wide', x: 0, y: 12, w: 12, h: 4 },
    ]

    function dragToTop(layoutCompaction: DashboardGridCompaction): Layout {
        const { result } = renderHook(() =>
            useDashboardLayoutInteraction({ layoutEditMode: true, layoutCompaction, updateLayouts: jest.fn() })
        )
        const compactor = result.current.gridCompactor
        let layout: Layout = baseline.map((item) => ({ ...item }))

        act(() => result.current.startInteraction(layout, getLayoutItem(layout, 'wide')!, 'drag'))
        // react-grid-layout feeds every intermediate row through the compactor, so the drag has to be
        // replayed frame by frame for path-dependent displacement to show up.
        for (let y = 11; y >= 0; y--) {
            const dragged = getLayoutItem(layout, 'wide')!
            layout = compactor.compact(
                moveElement(layout, dragged, dragged.x, y, true, false, compactor.type, COLS, compactor.allowOverlap),
                COLS
            )
        }
        act(() => result.current.finishInteraction())

        return compactor
            .compact(layout, COLS)
            .map(({ i, x, y, w, h }) => ({ i, x, y, w, h }))
            .sort((first, second) => first.i.localeCompare(second.i))
    }

    // Both modes share the collision resolver, so a drop resolves the same way in each.
    test.each([DashboardGridCompaction.Vertical, DashboardGridCompaction.Stable])(
        'keeps the tiles a drag passes over in place with %s compaction',
        (layoutCompaction) => {
            expect(dragToTop(layoutCompaction)).toEqual([
                { i: 'left-bottom', x: 0, y: 12, w: 6, h: 4 },
                { i: 'left-middle', x: 0, y: 8, w: 6, h: 4 },
                { i: 'left-top', x: 0, y: 4, w: 6, h: 4 },
                { i: 'right-bottom', x: 6, y: 12, w: 6, h: 4 },
                { i: 'right-middle', x: 6, y: 8, w: 6, h: 4 },
                { i: 'right-top', x: 6, y: 4, w: 6, h: 4 },
                { i: 'wide', x: 0, y: 0, w: 12, h: 4 },
            ])
        }
    )
})

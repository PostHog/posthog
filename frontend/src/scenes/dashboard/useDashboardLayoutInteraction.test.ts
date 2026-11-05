import { renderHook } from '@testing-library/react'
import type { Layout } from 'react-grid-layout'

import { useDashboardLayoutInteraction } from 'scenes/dashboard/useDashboardLayoutInteraction'

describe('useDashboardLayoutInteraction', () => {
    const layout: Layout = [{ i: '1', x: 0, y: 0, w: 6, h: 5 }]

    afterEach(() => {
        document.body.className = ''
    })

    test.each([
        ['the gesture finishes', (finish: () => void, _unmount: () => void) => finish()],
        ['the grid unmounts mid-gesture', (_finish: () => void, unmount: () => void) => unmount()],
    ])('releases the chart tooltip suppression when %s', (_, endGesture) => {
        const { result, unmount } = renderHook(() =>
            useDashboardLayoutInteraction({ layoutEditMode: true, updateLayouts: jest.fn() })
        )

        result.current.startInteraction(layout, layout[0], 'drag')
        expect(document.body.classList).toContain('dashboard-tile-interacting')

        endGesture(result.current.finishInteraction, unmount)
        expect(document.body.classList).not.toContain('dashboard-tile-interacting')
    })
})

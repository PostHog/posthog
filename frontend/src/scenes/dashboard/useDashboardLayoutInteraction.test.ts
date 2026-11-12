import { renderHook } from '@testing-library/react'
import type { Layout, LayoutItem } from 'react-grid-layout'

import { useDashboardLayoutInteraction } from './useDashboardLayoutInteraction'

const item: LayoutItem = { i: '1', x: 0, y: 0, w: 6, h: 5 }
const before: Layout = [item]
const moved = { sm: [{ ...item, x: 6 }] }
const movedAgain = { sm: [{ ...item, x: 3 }] }

describe('useDashboardLayoutInteraction', () => {
    let updateLayouts: jest.Mock

    beforeEach(() => {
        jest.useFakeTimers()
        updateLayouts = jest.fn()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    const renderInteraction = (enabled = true): ReturnType<typeof useDashboardLayoutInteraction> =>
        renderHook(() => useDashboardLayoutInteraction({ enabled, updateLayouts })).result.current

    it('ignores a layout the grid works out with no gesture', () => {
        const { handleLayoutChange } = renderInteraction()

        handleLayoutChange(null, moved)

        expect(updateLayouts).not.toHaveBeenCalled()
    })

    it('keeps the layout the grid reports right after a gesture, but not one that comes later', () => {
        const { handleLayoutChange, startInteraction, finishInteraction } = renderInteraction()

        startInteraction(before, item, 'drag')
        finishInteraction()
        handleLayoutChange(null, moved)
        expect(updateLayouts).toHaveBeenCalledWith(moved)

        jest.advanceTimersByTime(0)
        handleLayoutChange(null, movedAgain)
        expect(updateLayouts).toHaveBeenCalledTimes(1)
    })

    it('applies a layout reported during the gesture once the gesture ends', () => {
        const { handleLayoutChange, startInteraction, finishInteraction } = renderInteraction()

        startInteraction(before, item, 'resize')
        handleLayoutChange(null, moved)
        expect(updateLayouts).not.toHaveBeenCalled()

        finishInteraction()
        expect(updateLayouts).toHaveBeenCalledWith(moved)
    })

    it('drops the layout of a gesture whose tile left the grid', () => {
        const { handleLayoutChange, startInteraction, finishInteraction } = renderInteraction()

        startInteraction(before, item, 'drag')
        handleLayoutChange(null, moved)
        finishInteraction({ discardLayout: true })
        handleLayoutChange(null, movedAgain)

        expect(updateLayouts).not.toHaveBeenCalled()
    })

    it('ignores every layout when layout editing is off', () => {
        const { handleLayoutChange, startInteraction, finishInteraction } = renderInteraction(false)

        startInteraction(before, item, 'drag')
        handleLayoutChange(null, moved)
        finishInteraction()
        handleLayoutChange(null, movedAgain)

        expect(updateLayouts).not.toHaveBeenCalled()
    })
})

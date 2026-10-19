import { act, renderHook } from '@testing-library/react'

import { useDashboardContainerWidth } from './useDashboardContainerWidth'

describe('useDashboardContainerWidth', () => {
    it('keeps the grid width stable during continuous resize and commits the final rounded width', () => {
        jest.useFakeTimers()
        const originalObserver = global.ResizeObserver
        let notify: ResizeObserverCallback = () => {}
        const disconnect = jest.fn()
        global.ResizeObserver = jest.fn().mockImplementation((callback: ResizeObserverCallback) => {
            notify = callback
            return { observe: jest.fn(), disconnect }
        })
        const container = document.createElement('div')
        jest.spyOn(container, 'getBoundingClientRect').mockReturnValue({ width: 1200 } as DOMRect)
        const { result, unmount } = renderHook(() => {
            const measured = useDashboardContainerWidth()
            Object.assign(measured.containerRef, { current: container })
            return measured
        })

        try {
            expect(result.current.width).toBe(1200)
            for (const width of [1100, 1000, 900.4]) {
                act(() => {
                    notify([{ contentRect: { width } } as ResizeObserverEntry], {} as ResizeObserver)
                    jest.advanceTimersByTime(50)
                })
                expect(result.current.width).toBe(1200)
            }
            act(() => jest.advanceTimersByTime(50))
            expect(result.current.width).toBe(900)
            act(() => notify([{ contentRect: { width: 800 } } as ResizeObserverEntry], {} as ResizeObserver))
            document.body.classList.add('is-resizing')
            act(() => jest.advanceTimersByTime(500))
            expect(result.current.width).toBe(900)
            document.body.classList.remove('is-resizing')
            act(() => jest.advanceTimersByTime(100))
            expect(result.current.width).toBe(800)
            act(() => notify([{ contentRect: { width: 700 } } as ResizeObserverEntry], {} as ResizeObserver))
            unmount()
            expect(disconnect).toHaveBeenCalledTimes(1)
            expect(jest.getTimerCount()).toBe(0)
        } finally {
            document.body.classList.remove('is-resizing')
            global.ResizeObserver = originalObserver
            jest.useRealTimers()
        }
    })
})

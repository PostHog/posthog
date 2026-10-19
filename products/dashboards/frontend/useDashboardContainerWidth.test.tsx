import { act, renderHook } from '@testing-library/react'

import { useDashboardContainerWidth } from './useDashboardContainerWidth'

describe('useDashboardContainerWidth', () => {
    it('holds the latest width until release without letting unchanged widths delay it', () => {
        jest.useFakeTimers()
        const originalObserver = global.ResizeObserver
        let notify: ResizeObserverCallback = () => {}
        global.ResizeObserver = jest.fn().mockImplementation((callback: ResizeObserverCallback) => {
            notify = callback
            return { observe: jest.fn(), disconnect: jest.fn() }
        })
        const container = document.createElement('div')
        jest.spyOn(container, 'getBoundingClientRect').mockReturnValue({ width: 1200 } as DOMRect)
        const { result, unmount } = renderHook(() => {
            const measured = useDashboardContainerWidth()
            Object.assign(measured.containerRef, { current: container })
            return measured
        })

        try {
            document.body.classList.add('is-resizing')
            act(() => {
                for (const width of [900, 800]) {
                    notify([{ contentRect: { width } } as ResizeObserverEntry], {} as ResizeObserver)
                }
                jest.advanceTimersByTime(500)
            })
            expect(result.current.width).toBe(1200)

            document.body.classList.remove('is-resizing')
            for (const width of [800.4, 800.49]) {
                act(() => {
                    notify([{ contentRect: { width } } as ResizeObserverEntry], {} as ResizeObserver)
                    jest.advanceTimersByTime(8)
                })
            }
            expect(result.current.width).toBe(800)
        } finally {
            unmount()
            document.body.classList.remove('is-resizing')
            global.ResizeObserver = originalObserver
            jest.useRealTimers()
        }
    })
})

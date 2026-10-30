import { renderHook } from '@testing-library/react'

import { useDragAutoScroll } from './useDragAutoScroll'

describe('useDragAutoScroll', () => {
    let frames: FrameRequestCallback[]
    let container: HTMLDivElement

    beforeEach(() => {
        frames = []
        jest.spyOn(window, 'requestAnimationFrame').mockImplementation((callback: FrameRequestCallback) => {
            frames.push(callback)
            return frames.length
        })
        jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {})
        container = document.createElement('div')
        container.id = 'main-content'
        jest.spyOn(container, 'getBoundingClientRect').mockReturnValue({ top: 0, bottom: 1000 } as DOMRect)
        Object.defineProperty(container, 'clientHeight', { value: 1000 })
        Object.defineProperty(container, 'scrollHeight', { value: 3000 })
        Object.defineProperty(container, 'scrollTop', { value: 0, writable: true })
        container.scrollBy = jest.fn((_x: number, y: number) => {
            container.scrollTop += y
        }) as unknown as typeof container.scrollBy
        document.body.appendChild(container)
    })

    afterEach(() => {
        container.remove()
        jest.restoreAllMocks()
    })

    const runFrames = (count: number): void => {
        for (let i = 0; i < count && frames.length > 0; i++) {
            frames.shift()!(0)
        }
    }

    it.each([
        { name: 'scrolls down near the bottom edge until the end', clientY: 950, scrollTop: 1900, expected: 2000 },
        { name: 'scrolls up near the top edge until the start', clientY: 50, scrollTop: 100, expected: 0 },
        { name: 'does not scroll away from the edges', clientY: 500, scrollTop: 1000, expected: 1000 },
    ])('$name', ({ clientY, scrollTop, expected }) => {
        container.scrollTop = scrollTop
        const { result } = renderHook(() => useDragAutoScroll())

        result.current.startAutoScroll()
        result.current.autoScrollOnDrag(new MouseEvent('mousemove', { clientY }))
        runFrames(10)

        expect(container.scrollTop).toBe(expected)
        expect(frames).toHaveLength(0)
    })

    it('does nothing when the scroll container is missing', () => {
        container.remove()
        const { result } = renderHook(() => useDragAutoScroll())

        result.current.startAutoScroll()
        result.current.autoScrollOnDrag(new MouseEvent('mousemove', { clientY: 950 }))

        expect(frames).toHaveLength(0)
    })
})

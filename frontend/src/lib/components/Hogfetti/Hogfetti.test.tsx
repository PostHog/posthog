import { act, cleanup, render, renderHook } from '@testing-library/react'

import { useHogfetti } from './Hogfetti'

describe('useHogfetti', () => {
    afterEach(() => {
        cleanup()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    const mockReducedMotion = (reduced: boolean): void => {
        jest.spyOn(window, 'matchMedia').mockImplementation(
            (query: string) => ({ matches: reduced && query === '(prefers-reduced-motion: reduce)' }) as MediaQueryList
        )
    }

    it.each([
        { reducedMotion: true, expectedReturn: false, expectedHogs: 0 },
        { reducedMotion: false, expectedReturn: true, expectedHogs: 50 },
    ])(
        'with reduced motion $reducedMotion trigger returns $expectedReturn and draws $expectedHogs hogs',
        ({ reducedMotion, expectedReturn, expectedHogs }) => {
            mockReducedMotion(reducedMotion)
            const { result } = renderHook(() => useHogfetti())

            let animated: boolean | undefined
            act(() => {
                animated = result.current.trigger()
            })
            render(<result.current.HogfettiComponent />)

            expect(animated).toBe(expectedReturn)
            expect(document.body.querySelectorAll('.Hogfetti img')).toHaveLength(expectedHogs)
        }
    )

    it('mounts on the body so a host inside a stacking context still draws above modals', () => {
        mockReducedMotion(false)
        const { result } = renderHook(() => useHogfetti())
        act(() => {
            result.current.trigger()
        })

        render(
            <div className="relative z-10">
                <result.current.HogfettiComponent />
            </div>
        )

        expect(document.querySelector('.Hogfetti')?.parentElement).toBe(document.body)
    })

    it('stops scheduling animation frames once unmounted', () => {
        mockReducedMotion(false)
        jest.useFakeTimers()
        const requestFrame = jest.spyOn(window, 'requestAnimationFrame')
        const { result, unmount } = renderHook(() => useHogfetti())
        act(() => {
            result.current.trigger()
        })

        unmount()
        const framesScheduledAtUnmount = requestFrame.mock.calls.length
        act(() => {
            jest.advanceTimersByTime(100)
        })

        expect(framesScheduledAtUnmount).toBe(1)
        expect(requestFrame).toHaveBeenCalledTimes(framesScheduledAtUnmount)
    })

    it('draws nothing and schedules no frames when triggered after unmount', () => {
        mockReducedMotion(false)
        const requestFrame = jest.spyOn(window, 'requestAnimationFrame')
        const { result, unmount } = renderHook(() => useHogfetti())
        const { trigger } = result.current
        unmount()

        let animated: boolean | undefined
        act(() => {
            animated = trigger()
        })

        expect(animated).toBe(false)
        expect(requestFrame).not.toHaveBeenCalled()
    })
})

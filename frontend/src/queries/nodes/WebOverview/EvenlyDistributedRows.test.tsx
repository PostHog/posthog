import '@testing-library/jest-dom'

import { act, render } from '@testing-library/react'
import { Profiler } from 'react'

import { EvenlyDistributedRows } from './EvenlyDistributedRows'

describe('EvenlyDistributedRows', () => {
    let observedElement: Element | undefined
    let resizeCallback: ResizeObserverCallback
    let disconnectSpy: jest.Mock

    beforeEach(() => {
        observedElement = undefined
        disconnectSpy = jest.fn()

        class ResizeObserverMock {
            constructor(cb: ResizeObserverCallback) {
                resizeCallback = cb
            }
            observe(element: Element): void {
                observedElement = element
            }
            unobserve(): void {}
            disconnect(): void {
                disconnectSpy()
            }
        }
        ;(global as typeof globalThis & { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
            ResizeObserverMock as unknown as typeof ResizeObserver

        // Run rAF synchronously so a resize notification's effect is observable immediately.
        global.requestAnimationFrame = ((cb: FrameRequestCallback): number => {
            cb(0)
            return 0
        }) as typeof requestAnimationFrame
        global.cancelAnimationFrame = (() => {}) as typeof cancelAnimationFrame
    })

    // Triggers the ResizeObserver callback synchronously (act() flushes the rAF-scheduled state update).
    const triggerResize = (width: number): void => {
        act(() => {
            if (observedElement) {
                Object.defineProperty(observedElement, 'offsetWidth', { value: width, configurable: true })
            }
            resizeCallback([] as unknown as ResizeObserverEntry[], {} as ResizeObserver)
        })
    }

    it('does not re-render when a resize notification recomputes an unchanged layout', () => {
        // Use a Profiler rather than a child render counter: React bails out of re-rendering children
        // whose element reference is unchanged regardless of whether the parent's state actually
        // changed, so a child-level counter can't tell a real update apart from a no-op one.
        let commitCount = 0

        render(
            <Profiler id="test" onRender={() => commitCount++}>
                <EvenlyDistributedRows minWidthRems={5} className="">
                    {[<div key="a">a</div>, <div key="b">b</div>, <div key="c">c</div>]}
                </EvenlyDistributedRows>
            </Profiler>
        )

        // First resize genuinely changes the layout (mount computed it against jsdom's default 0 width).
        triggerResize(500)
        const commitCountAfterFirstResize = commitCount

        // Second notification reports the same width, so itemsPerRow is unchanged - this must not
        // commit another render (that's the oscillation that produces the "shaking" symptom).
        triggerResize(500)

        expect(commitCount).toBe(commitCountAfterFirstResize)
    })

    it('disconnects the observer on unmount', () => {
        const { unmount } = render(
            <EvenlyDistributedRows minWidthRems={5} className="">
                {[<div key="a">a</div>]}
            </EvenlyDistributedRows>
        )
        unmount()

        expect(disconnectSpy).toHaveBeenCalled()
    })
})

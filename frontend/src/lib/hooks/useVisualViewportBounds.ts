import { useEffect } from 'react'

/**
 * Publishes the browser's visual viewport – what's actually visible right now – as
 * `--visual-viewport-height` and `--visual-viewport-offset-top` on the document root.
 *
 * `dvh` already tracks collapsible mobile browser chrome, but no CSS unit tracks the on-screen
 * keyboard: it can halve the visible area while `dvh` doesn't budge. Anything that must stay fully
 * reachable while an input is focused (modals, whose scroll pane and footer otherwise end up below
 * the fold) needs these instead. The offset matters on iOS, where the visual viewport is scrolled
 * within the layout viewport that `position: fixed` resolves against.
 *
 * Written straight to the DOM rather than into React state so keyboard and pinch-zoom resizes don't
 * re-render the subscriber. Subscribers are ref-counted; the vars fall back to their `:root`
 * defaults once the last one unmounts.
 */
export function useVisualViewportBounds(enabled: boolean = true): void {
    useEffect(() => {
        if (!enabled) {
            return
        }
        subscriberCount += 1
        if (subscriberCount === 1) {
            attach()
        }
        return () => {
            subscriberCount -= 1
            if (subscriberCount === 0) {
                detach()
            }
        }
    }, [enabled])
}

let subscriberCount = 0
let teardown: (() => void) | null = null

function attach(): void {
    const visualViewport = window.visualViewport
    if (!visualViewport) {
        return
    }
    const update = (): void => {
        const { style } = document.documentElement
        style.setProperty('--visual-viewport-height', `${visualViewport.height}px`)
        style.setProperty('--visual-viewport-offset-top', `${visualViewport.offsetTop}px`)
    }
    update()
    visualViewport.addEventListener('resize', update)
    visualViewport.addEventListener('scroll', update)
    teardown = () => {
        visualViewport.removeEventListener('resize', update)
        visualViewport.removeEventListener('scroll', update)
        const { style } = document.documentElement
        style.removeProperty('--visual-viewport-height')
        style.removeProperty('--visual-viewport-offset-top')
    }
}

function detach(): void {
    teardown?.()
    teardown = null
}

import { useEffect } from 'react'

/** A phone keyboard is never shorter than this. Below it, treat the gap as scrollbar or rounding noise. */
const KEYBOARD_MIN_HEIGHT = 100

/**
 * Publishes how much of the layout viewport the on-screen keyboard is covering, as
 * `--keyboard-inset-bottom` and `--keyboard-inset-top` on the document root.
 *
 * `dvh` already tracks collapsible mobile browser chrome, but no CSS unit tracks the keyboard: it
 * can halve the visible area while `dvh` doesn't budge. Anything that must stay fully reachable
 * while an input is focused (modals, whose scroll pane and footer otherwise end up below the fold)
 * has to subtract these. The top inset matters on iOS, where the visual viewport is scrolled within
 * the layout viewport that `position: fixed` resolves against.
 *
 * Both are deltas that stay at their `0px` default unless a keyboard is genuinely up — never an
 * absolute measured height. `visualViewport.height` is legitimately smaller than the CSS viewport in
 * iframes and embedded contexts, so substituting it for `100dvh` there would clamp modals down and
 * clip their content.
 *
 * Written straight to the DOM rather than into React state so keyboard and pinch-zoom resizes don't
 * re-render the subscriber. Subscribers are ref-counted; the vars fall back to their `:root`
 * defaults once the last one unmounts.
 */
export function useKeyboardInsets(enabled: boolean = true): void {
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
        // Measure the whole occluded band before splitting it. A pan moves occlusion from below the
        // visible band to above it while the keyboard stays up, so a floor applied to the lower part
        // alone would drop the top inset and leave the modal stranded above the visible band.
        const occluded = document.documentElement.clientHeight - visualViewport.height
        if (occluded < KEYBOARD_MIN_HEIGHT) {
            clear()
            return
        }
        const top = Math.min(visualViewport.offsetTop, occluded)
        const { style } = document.documentElement
        style.setProperty('--keyboard-inset-bottom', `${occluded - top}px`)
        style.setProperty('--keyboard-inset-top', `${top}px`)
    }
    update()
    visualViewport.addEventListener('resize', update)
    visualViewport.addEventListener('scroll', update)
    teardown = () => {
        visualViewport.removeEventListener('resize', update)
        visualViewport.removeEventListener('scroll', update)
        clear()
    }
}

function detach(): void {
    teardown?.()
    teardown = null
}

function clear(): void {
    const { style } = document.documentElement
    style.removeProperty('--keyboard-inset-bottom')
    style.removeProperty('--keyboard-inset-top')
}

const MESSAGE_TOGGLE = '[data-attr="trace-view-message-toggle"]'
const EARLIER_MESSAGES = '[data-earlier-messages]'
const GAP_PX = 8

export type RevealMode = 'align' | 'ifBelow'

// The document never scrolls here: moving the page would take the trace header and the tree out of view.
function nearestScroller(element: HTMLElement): HTMLElement | null {
    for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
        const { overflowY } = getComputedStyle(parent)
        if ((overflowY === 'auto' || overflowY === 'scroll') && parent.scrollHeight > parent.clientHeight) {
            return parent
        }
    }
    return null
}

function prefersReducedMotion(): boolean {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

/** `ifBelow` scrolls only when the first open message is out of view below. The divider, when shown, goes to the top so the history above stays visible. */
export function revealFirstOpenMessage(container: HTMLElement | null, mode: RevealMode): void {
    const toggles = Array.from(container?.querySelectorAll<HTMLElement>(MESSAGE_TOGGLE) ?? [])
    const firstOpen = toggles.find((toggle) => toggle.getAttribute('aria-expanded') === 'true')
    if (!firstOpen || firstOpen === toggles[0]) {
        return
    }
    const scroller = nearestScroller(firstOpen)
    if (!scroller) {
        return
    }
    const scrollerRect = scroller.getBoundingClientRect()
    if (mode === 'ifBelow' && firstOpen.getBoundingClientRect().bottom <= scrollerRect.bottom) {
        return
    }
    const targetRect = (container?.querySelector<HTMLElement>(EARLIER_MESSAGES) ?? firstOpen).getBoundingClientRect()
    scroller.scrollTo({
        top: scroller.scrollTop + targetRect.top - scrollerRect.top - GAP_PX,
        behavior: mode === 'ifBelow' && !prefersReducedMotion() ? 'smooth' : 'auto',
    })
}

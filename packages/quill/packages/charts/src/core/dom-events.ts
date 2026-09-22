import type React from 'react'

export function originatesInElement(e: React.SyntheticEvent, selector: string): boolean {
    return e.target instanceof Element && !!e.target.closest(selector)
}

/** An interactive overlay child (a clickable marker, a node card) renders inside the same wrapper
 *  the chart's mousemove handler is bound to, so every hover over it still bubbles there. Without
 *  this guard the chart's own hover tracking fights the overlay for the cursor. An overlay opts out
 *  by marking its interactive root with this attribute. */
export function originatesInInteractiveOverlay(e: React.SyntheticEvent): boolean {
    return originatesInElement(e, '[data-hog-charts-interactive-overlay]')
}

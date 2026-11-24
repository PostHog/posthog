import type { LayoutItem } from 'react-grid-layout'

/** How far a tile at its minimum size gives way as the pointer keeps pushing, at most. */
const MAX_SQUEEZE_PX = 32
/** How fast it gives way: the pointer pushing this far past the edge gets about two thirds of the way to the most. */
const SQUEEZE_SCALE_PX = 40

/** The handle a resize started from, such as 'e' or 'sw', read from the handle the pointer pressed. */
export function resizeHandleOf(event: Event): string {
    const handle = event.target instanceof Element ? event.target.closest('.react-resizable-handle') : null
    return handle?.className.match(/react-resizable-handle-(\w+)/)?.[1] ?? ''
}

function squeeze(overshootPx: number): number {
    return MAX_SQUEEZE_PX * (1 - Math.exp(-Math.max(0, overshootPx) / SQUEEZE_SCALE_PX))
}

/**
 * Shows that a tile being resized has reached its minimum size. An overlay over the tile is outlined, and while the
 * pointer keeps pushing past the edge, it gives way a little toward the pointer, like a rubber band. The overlay is
 * drawn over the tile, so the tile and the layout never move.
 */
export function showResizeFeedback(tile: HTMLElement, item: LayoutItem, handle: string, event: Event): void {
    const atMinWidth = item.w <= (item.minW ?? 1)
    const atMinHeight = item.maxH === undefined && item.h <= (item.minH ?? 1)
    const pushingWidth = atMinWidth && /[ew]/.test(handle)
    const pushingHeight = atMinHeight && /[ns]/.test(handle)
    // An attribute, not a class, because the grid rewrites the tile's classes when the resize ends, which would cut
    // the spring back short.
    tile.toggleAttribute('data-dv2-at-minimum', pushingWidth || pushingHeight)

    const rect = tile.getBoundingClientRect()
    const pointer = event instanceof MouseEvent ? event : null
    const band = { top: 0, right: 0, bottom: 0, left: 0 }
    if (pointer && pushingWidth) {
        if (handle.includes('e')) {
            band.right = squeeze(rect.right - pointer.clientX)
        } else {
            band.left = squeeze(pointer.clientX - rect.left)
        }
    }
    if (pointer && pushingHeight) {
        if (handle.includes('s')) {
            band.bottom = squeeze(rect.bottom - pointer.clientY)
        } else {
            band.top = squeeze(pointer.clientY - rect.top)
        }
    }
    for (const [side, px] of Object.entries(band)) {
        tile.style.setProperty(`--dv2-band-${side}`, `${px}px`)
    }
    // The tile's content squeezes with the overlay, from the edge opposite the pointer. A transform leaves the layout
    // alone, so nothing around the tile moves.
    tile.style.setProperty('--dv2-squeeze-x', String((rect.width - band.left - band.right) / rect.width))
    tile.style.setProperty('--dv2-squeeze-y', String((rect.height - band.top - band.bottom) / rect.height))
    tile.style.setProperty(
        '--dv2-squeeze-origin',
        `${band.left > 0 ? 'right' : 'left'} ${band.top > 0 ? 'bottom' : 'top'}`
    )
}

/** Lets the overlay and the content spring back to the tile's edges, then removes the overlay. */
export function endResizeFeedback(tile: HTMLElement | null): void {
    if (!tile) {
        return
    }
    // The tile has no transition while it is resizing. Waiting two frames lets the grid drop its resizing class first,
    // so the reset animates instead of jumping.
    requestAnimationFrame(() =>
        requestAnimationFrame(() => {
            for (const side of ['top', 'right', 'bottom', 'left']) {
                tile.style.setProperty(`--dv2-band-${side}`, '0px')
            }
            tile.style.setProperty('--dv2-squeeze-x', '1')
            tile.style.setProperty('--dv2-squeeze-y', '1')
            // The spring back takes 300ms in DashboardV2.scss, so the overlay stays until then.
            setTimeout(() => tile.removeAttribute('data-dv2-at-minimum'), 300)
        })
    )
}

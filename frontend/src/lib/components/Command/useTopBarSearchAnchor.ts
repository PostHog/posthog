import { CSSProperties, useLayoutEffect, useState } from 'react'

const TOP_BAR_SEARCH_SELECTOR = '[data-attr="today-top-bar-search"]'
// The popup's 1px border, the input row's 8px padding, and half of the 32px input.
const POPUP_INPUT_CENTER_OFFSET = 25
// The popup border and the input row padding on each side, so the popup input lines up with the top bar field.
const POPUP_INPUT_INSET = 9
const MIN_POPUP_WIDTH = 640
const VIEWPORT_MARGIN = 24

/**
 * Places the palette over the top bar search field, so the field seems to open into the palette.
 * Returns undefined when the top bar has no search field, and the palette keeps its default place.
 */
export function useTopBarSearchAnchor(open: boolean): CSSProperties | undefined {
    const [anchor, setAnchor] = useState<CSSProperties | undefined>(undefined)

    useLayoutEffect(() => {
        if (!open) {
            setAnchor(undefined)
            return
        }
        const measure = (): void => {
            const field = document.querySelector<HTMLElement>(TOP_BAR_SEARCH_SELECTOR)
            const rect = field?.getBoundingClientRect()
            if (!rect || rect.width === 0) {
                setAnchor(undefined)
                return
            }
            const width = Math.min(
                Math.max(rect.width + 2 * POPUP_INPUT_INSET, MIN_POPUP_WIDTH),
                window.innerWidth - 2 * VIEWPORT_MARGIN
            )
            const center = Math.min(
                Math.max(rect.left + rect.width / 2, VIEWPORT_MARGIN + width / 2),
                window.innerWidth - VIEWPORT_MARGIN - width / 2
            )
            setAnchor({
                '--command-anchor-top': `${rect.top + rect.height / 2 - POPUP_INPUT_CENTER_OFFSET}px`,
                '--command-anchor-left': `${center}px`,
                '--command-anchor-width': `${width}px`,
            } as CSSProperties)
        }
        measure()
        window.addEventListener('resize', measure)
        return () => window.removeEventListener('resize', measure)
    }, [open])

    return anchor
}

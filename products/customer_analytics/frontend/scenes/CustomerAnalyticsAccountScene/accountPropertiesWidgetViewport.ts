import { RefCallback, useCallback, useLayoutEffect, useState } from 'react'

export const ACCOUNT_PROPERTIES_VISIBLE_ROW_LIMIT = 10

// Alert banners must not count toward the property limit.
const PROPERTY_ROW_SELECTOR = '[data-attr="account-property-row"], [data-attr="account-native-property-row"]'

export function getVisibleRowsHeight(
    content: HTMLElement,
    rowLimit = ACCOUNT_PROPERTIES_VISIBLE_ROW_LIMIT
): number | null {
    const rows = Array.from(content.children).filter((child): child is HTMLElement =>
        child.matches(PROPERTY_ROW_SELECTOR)
    )
    if (rows.length <= rowLimit) {
        return null
    }
    const lastVisibleRow = rows[rowLimit - 1]
    return Math.ceil(lastVisibleRow.getBoundingClientRect().bottom - content.getBoundingClientRect().top)
}

// Observe unclamped content to avoid resize feedback when the viewport height changes.
export function useAccountPropertiesViewport(): {
    contentRef: RefCallback<HTMLDivElement>
    maxHeight: number | null
} {
    const [content, setContent] = useState<HTMLDivElement | null>(null)
    const [maxHeight, setMaxHeight] = useState<number | null>(null)
    const contentRef = useCallback((element: HTMLDivElement | null) => setContent(element), [])

    // Row count can change without resizing the list.
    useLayoutEffect(() => {
        if (content) {
            const next = getVisibleRowsHeight(content)
            setMaxHeight((previous) => (previous === next ? previous : next))
        }
    })

    useLayoutEffect(() => {
        if (!content || typeof ResizeObserver === 'undefined') {
            return
        }
        const observer = new ResizeObserver(() => {
            const next = getVisibleRowsHeight(content)
            setMaxHeight((previous) => (previous === next ? previous : next))
        })
        observer.observe(content)
        return () => observer.disconnect()
    }, [content])

    return { contentRef, maxHeight }
}

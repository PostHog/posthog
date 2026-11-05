import { useLayoutEffect, useState } from 'react'

/**
 * Whether the element's rendered text contains the query. Reads the page text, the same text the search highlighter
 * marks, because the raw message differs from it (markdown syntax, escaped JSON).
 */
export function useShowsQuery(element: HTMLElement | null, query: string | null): boolean {
    const [showsQuery, setShowsQuery] = useState(false)
    useLayoutEffect(() => {
        if (!element || !query) {
            setShowsQuery(false)
            return
        }
        const needle = query.toLowerCase()
        const check = (): void => setShowsQuery((element.textContent ?? '').toLowerCase().includes(needle))
        check()
        const observer = new MutationObserver(check)
        observer.observe(element, { childList: true, subtree: true, characterData: true })
        return () => observer.disconnect()
    }, [element, query])
    return showsQuery
}

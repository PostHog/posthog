import './traceSearchHighlight.scss'

import { RefCallback, useEffect, useState } from 'react'

// pinned: the stylesheet styles `::highlight(trace-view-search)`
const HIGHLIGHT_NAME = 'trace-view-search'

function occurrences(container: HTMLElement, query: string): Range[] {
    const needle = query.toLowerCase()
    const ranges: Range[] = []
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const text = node.textContent ?? ''
        const haystack = text.toLowerCase()
        // Lowercasing can change the length of some characters, which would misplace every offset after them.
        if (haystack.length !== text.length) {
            continue
        }
        for (
            let index = haystack.indexOf(needle);
            index !== -1;
            index = haystack.indexOf(needle, index + needle.length)
        ) {
            const range = new Range()
            range.setStart(node, index)
            range.setEnd(node, index + needle.length)
            ranges.push(range)
        }
    }
    return ranges
}

/**
 * Marks each case-insensitive occurrence of the query in the text of the element the returned ref is attached to,
 * without changing the DOM.
 */
export function useSearchHighlight(query: string | null): RefCallback<HTMLElement> {
    const [element, setElement] = useState<HTMLElement | null>(null)
    useEffect(() => {
        if (!element || !query || typeof CSS === 'undefined' || !CSS.highlights) {
            return
        }
        const highlights = CSS.highlights
        const highlight = highlights.get(HIGHLIGHT_NAME) ?? new Highlight()
        highlights.set(HIGHLIGHT_NAME, highlight)
        let ranges: Range[] = []
        const mark = (): void => {
            ranges.forEach((range) => highlight.delete(range))
            ranges = occurrences(element, query)
            ranges.forEach((range) => highlight.add(range))
        }
        mark()
        // Steps load and tabs switch inside the container after the query is set.
        const observer = new MutationObserver(mark)
        observer.observe(element, { childList: true, subtree: true, characterData: true })
        return () => {
            observer.disconnect()
            ranges.forEach((range) => highlight.delete(range))
        }
    }, [element, query])
    return setElement
}

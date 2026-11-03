import './traceSearchHighlight.scss'

import { RefCallback, useEffect, useRef, useState } from 'react'

// pinned: the stylesheet styles `::highlight(trace-view-search)`
const HIGHLIGHT_NAME = 'trace-view-search'

// A query for a common character in a long message would otherwise create a range per character on every render.
export const MAX_HIGHLIGHTS = 500

interface TextRun {
    node: Node
    start: number
}

function boundary(runs: TextRun[], offset: number, side: 'start' | 'end'): [Node, number] {
    let low = 0
    let high = runs.length - 1
    while (low < high) {
        const middle = Math.ceil((low + high) / 2)
        const runStart = runs[middle].start
        if (side === 'start' ? runStart <= offset : runStart < offset) {
            low = middle
        } else {
            high = middle - 1
        }
    }
    return [runs[low].node, offset - runs[low].start]
}

/** Matches run across text nodes, because syntax highlighting splits a code line into one node per token. */
export function highlightRanges(container: HTMLElement, query: string): Range[] {
    const needle = query.toLowerCase()
    const runs: TextRun[] = []
    let haystack = ''
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const text = node.textContent ?? ''
        const lowered = text.toLowerCase()
        runs.push({ node, start: haystack.length })
        // Lowercasing can change the length of some characters, which would misplace every offset after them.
        haystack += lowered.length === text.length ? lowered : text
    }
    const ranges: Range[] = []
    for (
        let index = haystack.indexOf(needle);
        index !== -1 && ranges.length < MAX_HIGHLIGHTS;
        index = haystack.indexOf(needle, index + needle.length)
    ) {
        const range = new Range()
        range.setStart(...boundary(runs, index, 'start'))
        range.setEnd(...boundary(runs, index + needle.length, 'end'))
        ranges.push(range)
    }
    return ranges
}

function findOrCreateHighlight(highlights: HighlightRegistry): Highlight {
    const highlight = highlights.get(HIGHLIGHT_NAME) ?? new Highlight()
    highlights.set(HIGHLIGHT_NAME, highlight)
    return highlight
}

/**
 * Marks each case-insensitive occurrence of the query in the text of the element the returned ref is attached to,
 * without changing the DOM. When `revealKey` changes, the first occurrence scrolls into view once it renders.
 */
export function useSearchHighlight(query: string | null, revealKey: number = 0): RefCallback<HTMLElement> {
    const [element, setElement] = useState<HTMLElement | null>(null)
    const revealedKey = useRef(0)
    useEffect(() => {
        if (!element || !query) {
            return
        }
        const highlight = typeof CSS !== 'undefined' && CSS.highlights ? findOrCreateHighlight(CSS.highlights) : null
        let ranges: Range[] = []
        const mark = (): void => {
            ranges.forEach((range) => highlight?.delete(range))
            ranges = highlightRanges(element, query)
            ranges.forEach((range) => highlight?.add(range))
            if (ranges.length > 0 && revealedKey.current !== revealKey) {
                revealedKey.current = revealKey
                ranges[0].startContainer.parentElement?.scrollIntoView({ block: 'nearest' })
            }
        }
        mark()
        // Steps load and tabs switch inside the container after the query is set.
        const observer = new MutationObserver(mark)
        observer.observe(element, { childList: true, subtree: true, characterData: true })
        return () => {
            observer.disconnect()
            ranges.forEach((range) => highlight?.delete(range))
        }
    }, [element, query, revealKey])
    return setElement
}

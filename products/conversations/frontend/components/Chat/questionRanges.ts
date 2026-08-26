/** Elements the message renderers use to start a new line of text. A sentence never runs across one. */
const BLOCK_TAGS = new Set(['P', 'LI', 'DIV', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'BLOCKQUOTE', 'TD', 'TH', 'PRE'])

/** A sentence ending in one or more question marks, bounded by the previous sentence end or line break. */
const QUESTION = /[^.!?\n]*\?+/g

const HAS_LETTER = /\p{L}/u

interface Segment {
    node: Text
    /** Where this node's text starts in the flattened string. */
    start: number
}

function nearestBlock(node: Node): Element | null {
    let current = node.parentElement
    while (current) {
        if (BLOCK_TAGS.has(current.tagName)) {
            return current
        }
        current = current.parentElement
    }
    return null
}

/**
 * Flattens `root` into one string plus the map back to its text nodes. A block boundary or a `<br>` becomes a
 * newline, so a sentence can't run from the end of one paragraph into the start of the next.
 */
function flatten(root: HTMLElement): { text: string; segments: Segment[] } {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT)
    const segments: Segment[] = []
    let text = ''
    let previousBlock: Element | null = null
    let seenText = false

    let node = walker.nextNode()
    while (node) {
        if (node.nodeType === Node.ELEMENT_NODE) {
            if ((node as Element).tagName === 'BR') {
                text += '\n'
            }
        } else {
            const block = nearestBlock(node)
            if (seenText && block !== previousBlock) {
                text += '\n'
            }
            previousBlock = block
            seenText = true
            segments.push({ node: node as Text, start: text.length })
            text += node.nodeValue ?? ''
        }
        node = walker.nextNode()
    }

    return { text, segments }
}

/** Resolves a flattened offset to the text node and offset within it. */
function locate(segments: Segment[], offset: number): { node: Text; offset: number } | null {
    for (let i = segments.length - 1; i >= 0; i--) {
        const segment = segments[i]
        if (offset >= segment.start) {
            return { node: segment.node, offset: Math.min(offset - segment.start, segment.node.length) }
        }
    }
    return null
}

/**
 * Finds every sentence under `root` that ends in a question mark, as ranges over the rendered text nodes.
 *
 * Ranges rather than wrapper elements because both message renderers (TipTap and react-markdown) own their
 * DOM — the caller feeds these to the CSS Custom Highlight API, which needs no markup of its own.
 */
export function findQuestionRanges(root: HTMLElement): Range[] {
    const { text, segments } = flatten(root)
    if (!text.includes('?')) {
        return []
    }

    const ranges: Range[] = []
    QUESTION.lastIndex = 0
    let match = QUESTION.exec(text)
    while (match) {
        const leading = match[0].length - match[0].trimStart().length
        const start = match.index + leading
        const end = match.index + match[0].length

        if (HAS_LETTER.test(match[0])) {
            const from = locate(segments, start)
            const to = locate(segments, end)
            if (from && to) {
                const range = document.createRange()
                range.setStart(from.node, from.offset)
                range.setEnd(to.node, to.offset)
                ranges.push(range)
            }
        }

        match = QUESTION.exec(text)
    }

    return ranges
}

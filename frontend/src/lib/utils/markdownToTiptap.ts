import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import { MarkdownManager } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'

import { JSONContent } from 'lib/components/RichContentEditor/types'

const markdownManager = new MarkdownManager({
    extensions: [StarterKit, Table, TableRow, TableHeader, TableCell],
})

/**
 * Convert markdown string to tiptap JSONContent array using TipTap's official markdown parser.
 */
export function markdownToTiptap(markdown: string): JSONContent[] {
    if (!markdown || markdown.trim() === '') {
        return []
    }

    const doc = markdownManager.parse(markdown)

    // The parser returns a doc node with content array, we want just the content
    return (doc.content as JSONContent[]) || []
}

const MARKDOWN_BLOCK_PATTERNS: readonly RegExp[] = [
    /^#{1,6}\s+\S/m, // ATX heading
    /^[-*+]\s+\S/m, // unordered list item
    /^\d+\.\s+\S/m, // ordered list item
    /^>\s+\S/m, // blockquote
    /^```/m, // fenced code block
    /^~~~/m, // alt fenced code block
    /^\|.+\|/m, // table row
    /!\[[^\]]*\]\([^)]+\)/, // image
    /\[[^\]]+\]\([^)]+\)/, // link
]

/**
 * Heuristic check for whether a chunk of text looks like markdown that would
 * benefit from being parsed into rich nodes instead of pasted as plain text.
 * Intentionally conservative — only fires on strong, block-level signals so
 * that prose with stray characters (e.g. "use ** to emphasize") is not
 * misclassified.
 */
export function looksLikeMarkdown(text: string): boolean {
    if (!text || text.length < 3) {
        return false
    }
    return MARKDOWN_BLOCK_PATTERNS.some((pattern) => pattern.test(text))
}

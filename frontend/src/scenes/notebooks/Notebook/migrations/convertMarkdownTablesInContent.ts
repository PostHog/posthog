import { JSONContent } from '@tiptap/core'

import { parseMarkdownToTipTap } from 'lib/utils/parseMarkdownToTipTap'

// Plain text of an unstyled, text-only paragraph. Returns null for anything else
// (non-paragraphs, empty paragraphs, paragraphs with marks or non-text children) so
// we never rewrite a node whose meaning depends on more than its raw text.
function paragraphPlainText(node: JSONContent): string | null {
    if (node.type !== 'paragraph' || !Array.isArray(node.content)) {
        return null
    }
    let out = ''
    for (const child of node.content) {
        if (child.type !== 'text' || typeof child.text !== 'string') {
            return null
        }
        if (child.marks && child.marks.length > 0) {
            return null
        }
        out += child.text
    }
    return out
}

// A line that could be part of a markdown table: trimmed text wrapped in pipes with
// content between them. The real gate is whether the grouped run parses to a table,
// so this only needs to be loose enough to collect candidate rows.
function looksLikeTableLine(text: string): boolean {
    return /^\|.+\|$/.test(text.trim())
}

// Markdown tables typed directly into the editor land as one paragraph per row (and a
// table flattened onto a single line lands as one paragraph). Neither renders as a table.
// Group consecutive table-like paragraphs, parse them as markdown, and replace the run
// with the resulting table node when it parses cleanly.
export function convertMarkdownTablesInContent(content: JSONContent[]): JSONContent[] {
    const result: JSONContent[] = []
    let i = 0

    while (i < content.length) {
        const text = paragraphPlainText(content[i])
        if (text === null || !looksLikeTableLine(text)) {
            result.push(content[i])
            i++
            continue
        }

        // Collect the maximal run of consecutive table-like paragraphs.
        const run: JSONContent[] = []
        const texts: string[] = []
        while (i < content.length) {
            const lineText = paragraphPlainText(content[i])
            if (lineText === null || !looksLikeTableLine(lineText)) {
                break
            }
            run.push(content[i])
            texts.push(lineText.trim())
            i++
        }

        const parsedContent = parseMarkdownToTipTap(texts.join('\n'))
        const isTable = parsedContent.length > 0 && parsedContent.every((node) => node.type === 'table')

        result.push(...(isTable ? parsedContent : run))
    }

    return result
}

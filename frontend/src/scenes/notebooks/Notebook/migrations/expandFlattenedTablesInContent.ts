import { JSONContent } from '@tiptap/core'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import { MarkdownManager } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'

import { expandFlattenedMarkdownTables } from 'lib/utils/expandFlattenedMarkdownTables'

const markdownManager = new MarkdownManager({
    extensions: [StarterKit, Table, TableRow, TableHeader, TableCell],
})

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

export function expandFlattenedTablesInContent(content: JSONContent[]): JSONContent[] {
    return content.flatMap((node) => {
        const text = paragraphPlainText(node)
        if (text === null) {
            return [node]
        }
        const expanded = expandFlattenedMarkdownTables(text)
        if (expanded === text) {
            return [node]
        }
        const parsed = markdownManager.parse(expanded) as JSONContent
        const parsedContent = (parsed.content as JSONContent[] | undefined) ?? []
        if (parsedContent.length === 0) {
            return [node]
        }
        return parsedContent
    })
}

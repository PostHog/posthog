import { JSONContent } from '@tiptap/core'
import { Link } from '@tiptap/extension-link'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import { MarkdownManager } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'

import { expandFlattenedMarkdownTables } from 'lib/utils/markdown'

const markdownManager = new MarkdownManager({
    extensions: [
        StarterKit.configure({ link: false }),
        Link,
        Table,
        TableRow,
        TableHeader,
        TableCell,
        TaskList,
        TaskItem.configure({ nested: true }),
    ],
})

// Parse a markdown string into TipTap JSONContent nodes, first expanding any flattened
// tables (rows glued onto one line) so they render as real tables. Shared by the paste
// handler and the notebook migration so both stay consistent.
export function parseMarkdownToTipTap(markdown: string): JSONContent[] {
    if (!markdown || markdown.trim() === '') {
        return []
    }
    const doc = markdownManager.parse(expandFlattenedMarkdownTables(markdown)) as JSONContent
    return (doc.content as JSONContent[]) || []
}

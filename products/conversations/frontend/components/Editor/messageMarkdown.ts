import { JSONContent } from '@tiptap/core'

import { MARKDOWN_BASE_EDITABLE_EXTENSIONS } from 'lib/components/MarkdownEditor/shared/markdownExtensions'
import { createTiptapMarkdownConverter } from 'lib/utils/markdown'

// Parsing runs on the shared markdown extension set rather than SUPPORT_EXTENSIONS, which
// MarkdownManager cannot build a schema from. That set covers more than the support editor renders,
// which is what canEditMessageBody screens for.
const converter = createTiptapMarkdownConverter(MARKDOWN_BASE_EDITABLE_EXTENSIONS)

/** Nodes and marks the support editor can hold. Anything outside this is dropped when the editor
 * loads a document, so the note would come back short on the next save. */
const REPRESENTABLE_TYPES = new Set([
    'doc',
    'paragraph',
    'text',
    'hardBreak',
    'bulletList',
    'orderedList',
    'listItem',
    'codeBlock',
    'image',
    'ph-mention',
    'bold',
    'italic',
    'code',
    'link',
    'underline',
])

/** Parse a stored message body (markdown) into editor content. Messages posted through the ticket
 * reply API, and ones carried in by an import, have only this markdown: loading it as literal text
 * instead would send it back through the editor's markdown escaping on save, so `**urgent**` would
 * be stored as `\*\*urgent\*\*` and stop rendering as bold. */
export function messageBodyToRichContent(content: string): JSONContent {
    return converter.markdownToDoc(content)
}

function isRepresentable(node: JSONContent): boolean {
    if (node.type && !REPRESENTABLE_TYPES.has(node.type)) {
        return false
    }
    if (node.marks?.some((mark) => !REPRESENTABLE_TYPES.has(mark.type))) {
        return false
    }
    return (node.content ?? []).every(isRepresentable)
}

/** A table's delimiter row, matched per line. Nothing in the parse set implements tables, so a table
 * is dropped during parsing instead of surfacing as an unrepresentable node, which means it has to
 * be recognised from the markdown itself. Mirrors the delimiter shape used in lib/utils/markdown. */
const MARKDOWN_TABLE_DELIMITER_ROW = /^\|(?:\s*:?-{2,}:?\s*\|)+\s*$/m

/** Whether the support editor can load a message body without losing part of it. A body stored as
 * markdown may use constructs the editor doesn't render, such as a heading or a table, and opening
 * one of those would drop it from the note on the next save. Bodies that already have rich content
 * came from this editor, so they always load. */
export function canEditMessageBody(content: string | null | undefined, richContent: unknown): boolean {
    if (richContent) {
        return true
    }
    if (!content?.trim()) {
        return false
    }
    if (MARKDOWN_TABLE_DELIMITER_ROW.test(content)) {
        return false
    }
    const parsed = messageBodyToRichContent(content)
    // An empty parse means the whole body was made of constructs that were dropped, so there would
    // be nothing left to save back.
    return (parsed.content?.length ?? 0) > 0 && isRepresentable(parsed)
}

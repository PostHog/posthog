import { JSONContent } from '@tiptap/core'
import { generateHTML } from '@tiptap/html'

import { SUPPORT_PREVIEW_EXTENSIONS } from './SupportEditor'

/**
 * Render a message's rich content as HTML, for putting on the clipboard alongside the plain-text
 * markdown form.
 *
 * A message's plain-text field is markdown, and nothing that receives a paste parses markdown out
 * of it. The reply composer is a ProseMirror editor with no markdown paste parser, so pasted text
 * goes through ProseMirror's default handling, which splits on each run of newlines and makes
 * every block a plain paragraph. A blank line, a line break, and a list item all end up as the
 * same ordinary paragraph boundary, and markdown syntax plus the backslash escapes that
 * `serializeToMarkdown` adds arrive as literal text. HTML is the format both the composer and
 * mail clients already know how to parse.
 *
 * Returns null when the content cannot be rendered against the preview schema, in which case
 * callers should copy the plain-text form on its own.
 */
export function richContentToHtml(content: JSONContent | null | undefined): string | null {
    if (!content) {
        return null
    }
    try {
        return generateHTML(content, [...SUPPORT_PREVIEW_EXTENSIONS])
    } catch {
        return null
    }
}

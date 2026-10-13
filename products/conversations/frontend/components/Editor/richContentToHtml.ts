import { JSONContent, mergeAttributes } from '@tiptap/core'
import { generateHTML } from '@tiptap/html'

import { RichContentNodeMention } from 'lib/components/RichContentEditor/RichContentNodeMention'
import { RichContentNodeType } from 'lib/components/RichContentEditor/types'

import { isRenderableRichContent } from './isRenderableRichContent'
import { SUPPORT_PREVIEW_EXTENSIONS } from './SupportEditor'

/**
 * A mention normally shows a member's name through a React node view, which never runs during
 * plain HTML generation. Without a text child the element serializes empty, so a paste target that
 * does not know the `ph-mention` tag, such as a mail client, drops the mention and loses a word
 * from the sentence. The composer parses the node back from the tag and ignores this text, so it
 * only shows up outside PostHog, where it matches what the markdown form has always carried.
 */
const ClipboardMention = RichContentNodeMention.extend({
    renderHTML({ HTMLAttributes, node }) {
        return [RichContentNodeType.Mention, mergeAttributes(HTMLAttributes), `@member:${node.attrs.id}`]
    },
})

const CLIPBOARD_EXTENSIONS = SUPPORT_PREVIEW_EXTENSIONS.map((extension) =>
    extension.name === RichContentNodeMention.name ? ClipboardMention : extension
)

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
 * callers should copy the plain-text form on its own. That is the same verdict the reader sees,
 * because `generateHTML` builds the document without checking it against the schema and would
 * otherwise put content on the clipboard that the message never displayed.
 */
export function richContentToHtml(content: JSONContent | null | undefined): string | null {
    if (!isRenderableRichContent(content)) {
        return null
    }
    try {
        return generateHTML(content, CLIPBOARD_EXTENSIONS)
    } catch {
        return null
    }
}

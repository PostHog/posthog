import { MarkdownManager } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'

import { JSONContent } from 'lib/components/RichContentEditor/types'

// Create a singleton MarkdownManager with the same extensions used in notebooks
const markdownManager = new MarkdownManager({
    extensions: [StarterKit],
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

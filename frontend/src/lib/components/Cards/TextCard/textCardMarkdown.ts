import { JSONContent } from '@tiptap/core'
import { Image } from '@tiptap/extension-image'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { MarkdownManager } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'

const markdownManager = new MarkdownManager({
    extensions: [StarterKit, TaskList, TaskItem.configure({ nested: true }), Image],
})

const EMPTY_DOC_CONTENT: JSONContent['content'] = [{ type: 'paragraph' }]

export const EMPTY_TEXT_CARD_DOC: JSONContent = {
    type: 'doc',
    content: EMPTY_DOC_CONTENT,
}

export function markdownToTextCardDoc(markdown: string | null | undefined): JSONContent {
    if (!markdown || markdown.trim() === '') {
        return EMPTY_TEXT_CARD_DOC
    }

    try {
        const parsed = markdownManager.parse(markdown) as JSONContent
        if (parsed.type === 'doc') {
            return parsed
        }
    } catch {
        // Fall through to plain paragraph fallback for malformed legacy markdown.
    }

    return {
        type: 'doc',
        content: [
            {
                type: 'paragraph',
                content: [{ type: 'text', text: markdown }],
            },
        ],
    }
}

export function textCardDocToMarkdown(doc: JSONContent): string {
    try {
        return markdownManager.serialize(doc).trimEnd()
    } catch {
        return ''
    }
}

export function isTextCardMarkdownRoundTripSafe(markdown: string | null | undefined): boolean {
    if (!markdown || markdown.trim() === '') {
        return true
    }

    try {
        const originalDoc = markdownToTextCardDoc(markdown)
        const roundTripDoc = markdownToTextCardDoc(textCardDocToMarkdown(originalDoc))
        return JSON.stringify(originalDoc) === JSON.stringify(roundTripDoc)
    } catch {
        return false
    }
}

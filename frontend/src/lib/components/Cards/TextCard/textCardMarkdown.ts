import { JSONContent } from '@tiptap/core'
import { Image } from '@tiptap/extension-image'
import { Link } from '@tiptap/extension-link'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { MarkdownManager } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'

function escapeHtmlAttribute(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
}

const TextCardImageExtension = Image.extend({
    renderMarkdown(node) {
        const attrs = node.attrs || {}
        const src = attrs.src || ''
        const alt = attrs.alt || ''
        const title = attrs.title || ''
        const width = attrs.width
        const height = attrs.height

        if (!width && !height) {
            return title ? `![${alt}](${src} "${title}")` : `![${alt}](${src})`
        }

        const htmlAttrs = [
            `src="${escapeHtmlAttribute(String(src))}"`,
            `alt="${escapeHtmlAttribute(String(alt))}"`,
            ...(title ? [`title="${escapeHtmlAttribute(String(title))}"`] : []),
            ...(width ? [`width="${escapeHtmlAttribute(String(width))}"`] : []),
            ...(height ? [`height="${escapeHtmlAttribute(String(height))}"`] : []),
        ]

        return `<img ${htmlAttrs.join(' ')} />`
    },
})

const TEXT_CARD_MARKDOWN_BASE_EXTENSIONS = [
    StarterKit.configure({
        heading: {
            levels: [1, 2, 3],
        },
        link: false,
    }),
    TaskList,
    TaskItem.configure({ nested: true }),
]

const TEXT_CARD_MARKDOWN_BASE_EDITABLE_EXTENSIONS = [
    ...TEXT_CARD_MARKDOWN_BASE_EXTENSIONS,
    Link.configure({ openOnClick: false }),
]

const TEXT_CARD_MARKDOWN_BASE_READONLY_EXTENSIONS = [
    ...TEXT_CARD_MARKDOWN_BASE_EXTENSIONS,
    Link.configure({ openOnClick: true }),
]

export const TEXT_CARD_MARKDOWN_EXTENSIONS = [
    ...TEXT_CARD_MARKDOWN_BASE_EDITABLE_EXTENSIONS,
    TextCardImageExtension.configure({
        HTMLAttributes: {
            draggable: 'true',
        },
        resize: {
            enabled: true,
            directions: ['top', 'bottom', 'left', 'right'],
            minWidth: 50,
            minHeight: 50,
            alwaysPreserveAspectRatio: true,
        },
    }),
]

export const TEXT_CARD_MARKDOWN_READONLY_EXTENSIONS = [
    ...TEXT_CARD_MARKDOWN_BASE_READONLY_EXTENSIONS,
    TextCardImageExtension.configure({
        HTMLAttributes: {
            draggable: 'false',
        },
        resize: {
            enabled: false,
        },
    }),
]

const markdownManager = new MarkdownManager({
    extensions: TEXT_CARD_MARKDOWN_EXTENSIONS,
})

const EMPTY_DOC_CONTENT: JSONContent['content'] = [{ type: 'paragraph' }]

export const EMPTY_TEXT_CARD_DOC: JSONContent = {
    type: 'doc',
    content: EMPTY_DOC_CONTENT,
}

function isEffectivelyEmptyTextCardDoc(doc: JSONContent): boolean {
    if (doc.type !== 'doc') {
        return false
    }

    if (!doc.content || doc.content.length === 0) {
        return true
    }

    if (doc.content.length !== 1 || doc.content[0].type !== 'paragraph') {
        return false
    }

    const paragraphContent = doc.content[0].content
    if (!paragraphContent || paragraphContent.length === 0) {
        return true
    }

    return paragraphContent.every((node) => node.type === 'text' && !node.text)
}

export function markdownToTextCardDoc(markdown: string | null | undefined): JSONContent {
    if (!markdown) {
        return EMPTY_TEXT_CARD_DOC
    }

    if (markdown.trim() === '') {
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
        if (isEffectivelyEmptyTextCardDoc(doc)) {
            return ''
        }

        const markdown = markdownManager.serialize(doc).trimEnd()
        if (!markdown) {
            return ''
        }
        return markdown
    } catch {
        return ''
    }
}

export function isTextCardMarkdownRoundTripSafe(markdown: string | null | undefined): boolean {
    if (!markdown || markdown.trim() === '') {
        return true
    }

    try {
        const originalDoc = markdownManager.parse(markdown) as JSONContent
        const roundTripDoc = markdownManager.parse(markdownManager.serialize(originalDoc).trimEnd()) as JSONContent
        return JSON.stringify(originalDoc) === JSON.stringify(roundTripDoc)
    } catch {
        return false
    }
}

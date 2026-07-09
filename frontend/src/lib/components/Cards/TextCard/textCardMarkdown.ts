import { JSONContent } from '@tiptap/core'
import { Image } from '@tiptap/extension-image'
import { Link } from '@tiptap/extension-link'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { MarkdownManager } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'

import { expandFlattenedMarkdownTables } from 'lib/utils/markdown'

import { WordArtExtension } from './WordArt/WordArtExtension'

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
    WordArtExtension,
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

// @tiptap/markdown closes a text node's marks in array order, so when `code` is not the
// innermost mark it emits malformed markdown (e.g. **`snippet**` instead of **`snippet`**).
// That broke the round trip and made the controlled editor reset itself while typing. Force
// `code` innermost (first in the marks array) so its backticks always sit inside bold/italic/strike.
function withCodeMarkInnermost(doc: JSONContent): JSONContent {
    const visit = (node: JSONContent): JSONContent => {
        let next = node
        const marks = node.marks
        if (marks && marks.length > 1 && marks.some((mark) => mark.type === 'code')) {
            const code = marks.filter((mark) => mark.type === 'code')
            const others = marks.filter((mark) => mark.type !== 'code')
            next = { ...node, marks: [...code, ...others] }
        }
        if (next.content) {
            next = { ...next, content: next.content.map(visit) }
        }
        return next
    }
    return visit(doc)
}

function serializeTextCardDoc(doc: JSONContent): string {
    return markdownManager.serialize(withCodeMarkInnermost(doc))
}

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
        const parsed = markdownManager.parse(expandFlattenedMarkdownTables(markdown)) as JSONContent
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

        const markdown = serializeTextCardDoc(doc).trimEnd()
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
        const expanded = expandFlattenedMarkdownTables(markdown)
        const originalDoc = markdownManager.parse(expanded) as JSONContent
        const roundTripDoc = markdownManager.parse(serializeTextCardDoc(originalDoc).trimEnd()) as JSONContent
        return JSON.stringify(originalDoc) === JSON.stringify(roundTripDoc)
    } catch {
        return false
    }
}

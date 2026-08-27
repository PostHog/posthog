import { JSONContent } from '@tiptap/core'
import { Image } from '@tiptap/extension-image'

import {
    MARKDOWN_BASE_EDITABLE_EXTENSIONS,
    MARKDOWN_BASE_READONLY_EXTENSIONS,
} from 'lib/components/MarkdownEditor/shared/markdownExtensions'
import { createTiptapMarkdownConverter, TiptapMarkdownConverter } from 'lib/utils/markdown'

import { WordArtExtension } from './WordArt/WordArtExtension'

type Mark = NonNullable<JSONContent['marks']>[number]

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

export const TEXT_CARD_MARKDOWN_EXTENSIONS = [
    ...MARKDOWN_BASE_EDITABLE_EXTENSIONS,
    WordArtExtension,
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
    ...MARKDOWN_BASE_READONLY_EXTENSIONS,
    WordArtExtension,
    TextCardImageExtension.configure({
        HTMLAttributes: {
            draggable: 'false',
        },
        resize: {
            enabled: false,
        },
    }),
]

// The `@tiptap/markdown` parser leaves a link written inside a code span as literal text: it keeps
// `[label](url)` visible instead of making it clickable. These helpers promote such a code span into
// a text node that carries both a `code` and a `link` mark, the same shape the parser already
// produces for `[`label`](url)`, so authors get a link whichever way they nest the backticks.
const CODE_SPAN_LINK_RE = /^\[([^\]]+)\]\(([^)\s]+)\)$/
const BARE_URL_RE = /^https?:\/\/\S+$/

function isCodeMarked(node: JSONContent): boolean {
    return node.type === 'text' && !!node.marks?.some((mark) => mark.type === 'code')
}

function hasLinkMark(node: JSONContent): boolean {
    return !!node.marks?.some((mark) => mark.type === 'link')
}

// Ask the parser for the exact `link` mark it emits for a given href, so we match its attrs.
function linkMarkForHref(converter: TiptapMarkdownConverter, href: string): Mark | null {
    const doc = converter.markdownToDoc(`[link](${href})`)
    const textNode = doc.content?.[0]?.content?.[0]
    return textNode?.marks?.find((mark) => mark.type === 'link') ?? null
}

function promoteCodeSpanLinks(converter: TiptapMarkdownConverter, doc: JSONContent): JSONContent {
    const visit = (node: JSONContent): JSONContent => {
        // Skip a code span the parser already linked (the `[`label`](url)` case). Promoting it again
        // appends a second link mark, and when the label is itself a URL the serializer then writes
        // the label URL back as the href, silently replacing the author's target.
        if (isCodeMarked(node) && !hasLinkMark(node) && node.text) {
            const match = CODE_SPAN_LINK_RE.exec(node.text)
            const [label, href] = match
                ? [match[1], match[2]]
                : BARE_URL_RE.test(node.text)
                  ? [node.text, node.text]
                  : []
            if (href) {
                const linkMark = linkMarkForHref(converter, href)
                if (linkMark) {
                    return { ...node, text: label, marks: [...(node.marks ?? []), linkMark] }
                }
            }
        }
        if (node.content) {
            return { ...node, content: node.content.map(visit) }
        }
        return node
    }

    return visit(doc)
}

const baseTextCardConverter = createTiptapMarkdownConverter(TEXT_CARD_MARKDOWN_EXTENSIONS)

export const textCardConverter: TiptapMarkdownConverter = {
    ...baseTextCardConverter,
    markdownToDoc: (markdown) =>
        promoteCodeSpanLinks(baseTextCardConverter, baseTextCardConverter.markdownToDoc(markdown)),
}

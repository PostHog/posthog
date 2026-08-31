import { JSONContent } from '@tiptap/core'
import { Image } from '@tiptap/extension-image'
import { isAllowedUri } from '@tiptap/extension-link'

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
const CODE_SPAN_LINK_RE = /^\[([^\]]+)\]\((<[^>\s]+>|[^)\s]+)\)$/
const BARE_URL_RE = /^https?:\/\/\S+$/

// Markdown lets a link destination sit in angle brackets, as in `[label](<url>)`. The brackets are
// syntax, not part of the address, so drop them before they reach the href. Neither form of
// destination holds whitespace, which is why both arms of the pattern above exclude it.
function unwrapDestination(destination: string): string {
    return destination.startsWith('<') && destination.endsWith('>') ? destination.slice(1, -1) : destination
}

function codeSpanLink(text: string): { label: string; href: string } | null {
    const match = CODE_SPAN_LINK_RE.exec(text)
    if (match) {
        return { label: match[1], href: unwrapDestination(match[2]) }
    }
    return BARE_URL_RE.test(text) ? { label: text, href: text } : null
}

function isCodeMarked(node: JSONContent): boolean {
    return node.type === 'text' && !!node.marks?.some((mark) => mark.type === 'code')
}

function hasLinkMark(node: JSONContent): boolean {
    return !!node.marks?.some((mark) => mark.type === 'link')
}

const baseTextCardConverter = createTiptapMarkdownConverter(TEXT_CARD_MARKDOWN_EXTENSIONS)

// Sample the `link` mark the parser emits, so a promoted node carries the attrs the parser would
// have given it. Only `href` varies with the destination, and promotion sets that itself, so one
// sample serves every link.
const parsedLinkMark: Mark | undefined = baseTextCardConverter
    .markdownToDoc('[link](https://example.com)')
    .content?.[0]?.content?.[0]?.marks?.find((mark) => mark.type === 'link')

function promoteCodeSpanLinks(doc: JSONContent): JSONContent {
    const visit = (node: JSONContent): JSONContent => {
        if (node.content) {
            return { ...node, content: node.content.map(visit) }
        }
        // Skip a code span the parser already linked (the `[`label`](url)` case). Promoting it again
        // appends a second link mark, and when the label is itself a URL the serializer then writes
        // the label URL back as the href, silently replacing the author's target.
        if (!parsedLinkMark || !isCodeMarked(node) || hasLinkMark(node) || !node.text) {
            return node
        }
        const link = codeSpanLink(node.text)
        // Promotion writes the destination straight onto the href, so it applies the link mark's own
        // protocol allowlist here. Reusing that check keeps promotion and rendering in agreement.
        if (!link || !isAllowedUri(link.href)) {
            return node
        }
        const mark = { ...parsedLinkMark, attrs: { ...parsedLinkMark.attrs, href: link.href } }
        return { ...node, text: link.label, marks: [...(node.marks ?? []), mark] }
    }

    return visit(doc)
}

export const textCardConverter: TiptapMarkdownConverter = {
    ...baseTextCardConverter,
    markdownToDoc: (markdown) => promoteCodeSpanLinks(baseTextCardConverter.markdownToDoc(markdown)),
}

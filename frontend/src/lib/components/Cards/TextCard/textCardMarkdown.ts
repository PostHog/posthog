import { JSONContent } from '@tiptap/core'
import { Image } from '@tiptap/extension-image'
import { isAllowedUri, LinkOptions } from '@tiptap/extension-link'

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
const CODE_SPAN_LINK_RE = /^\[([^\]]+)\]\((<[^>]+>|[^)\s]+)\)$/
const BARE_URL_RE = /^https?:\/\/\S+$/

// Markdown lets a link destination sit in angle brackets, as in `[label](<url>)`. The brackets are
// syntax, not part of the address, so drop them before they reach the href.
function unwrapDestination(destination: string): string {
    return destination.startsWith('<') && destination.endsWith('>') ? destination.slice(1, -1) : destination
}

// Promotion writes the matched destination straight onto the href, so it has to apply the protocol
// allowlist itself. Reuse the link mark's own check, reading the protocols off the configured
// extension, so the promotion gate and the render gate cannot drift apart.
const linkOptions = MARKDOWN_BASE_EDITABLE_EXTENSIONS.find((extension) => extension.name === 'link')?.options as
    | Pick<LinkOptions, 'protocols'>
    | undefined

function hasRenderableScheme(href: string): boolean {
    return !!isAllowedUri(href, linkOptions?.protocols)
}

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
                ? [match[1], unwrapDestination(match[2])]
                : BARE_URL_RE.test(node.text)
                  ? [node.text, node.text]
                  : []
            if (href && hasRenderableScheme(href)) {
                const linkMark = linkMarkForHref(converter, href)
                if (linkMark) {
                    // Keep the href we matched, not the parser's round-tripped copy. A bare URL that
                    // ends in an unbalanced `)` loses that character in the round trip, so the link
                    // would point one step short of the URL the card shows.
                    const mark = { ...linkMark, attrs: { ...linkMark.attrs, href } }
                    return { ...node, text: label, marks: [...(node.marks ?? []), mark] }
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

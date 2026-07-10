import { JSONContent } from '@tiptap/core'
import { MarkdownManager } from '@tiptap/markdown'
import { Extensions } from '@tiptap/react'
import { marked } from 'marked'

const TABLE_DELIMITER_SEGMENT_RE = /^\|(?:\s*:?-{2,}:?\s*\|)+\s*$/
// Matches the boundary between two flattened rows: a closing `|` directly followed by the
// next row's opening `|`. The whitespace is optional because some sources (e.g. AI chat
// output) glue rows together with no space (`...Total ||-------|...`) while others keep one.
const FLATTENED_TABLE_ROW_BOUNDARY_RE = /(?<=\|)\s*(?=\|)/

// Slack, ChatGPT, Notion etc. strip newlines between table rows on plain-text copy.
// Only splits when a delimiter row (`|---|---|`) is present, so prose with `|` is safe.
export function expandFlattenedMarkdownTables(text: string): string {
    return text
        .split('\n')
        .flatMap((line) => {
            const segments = line.split(FLATTENED_TABLE_ROW_BOUNDARY_RE).map((s) => s.trim())
            if (segments.length < 2 || !segments.some((s) => TABLE_DELIMITER_SEGMENT_RE.test(s))) {
                return [line]
            }
            return segments
        })
        .join('\n')
}

type Token = ReturnType<typeof marked.lexer>[number]

function resolveUrl(href: string): string {
    if (!href) {
        return href
    }
    // Already absolute
    if (href.startsWith('http://') || href.startsWith('https://')) {
        return href
    }
    // Relative URL - prefix with current origin
    if (typeof window !== 'undefined') {
        return new URL(href, window.location.origin).href
    }
    return href
}

/**
 * Converts markdown text to plain text by removing all markdown formatting
 */
export function stripMarkdown(markdown: string): string {
    // Parse markdown to tokens
    const tokens = marked.lexer(markdown)

    // Extract text from tokens recursively
    const extractText = (token: Token): string => {
        switch (token.type) {
            case 'paragraph':
                return 'tokens' in token && Array.isArray(token.tokens)
                    ? token.tokens.map(extractText).join('')
                    : 'text' in token
                      ? String(token.text)
                      : ''

            case 'text':
                return 'tokens' in token && Array.isArray(token.tokens)
                    ? token.tokens.map(extractText).join('')
                    : 'text' in token
                      ? String(token.text)
                      : ''

            case 'heading':
                return token.tokens ? token.tokens.map(extractText).join('') : ''

            case 'list':
                return token.items
                    .map((item: any, index: number) => {
                        const prefix = token.ordered ? `${(token.start || 1) + index}. ` : '- '
                        return prefix + item.tokens.map(extractText).join('')
                    })
                    .join('\n')

            case 'list_item':
                return token.tokens ? token.tokens.map(extractText).join('') : ''

            case 'blockquote':
                return token.tokens ? token.tokens.map(extractText).join('') : ''

            case 'code':
                return token.text

            case 'codespan':
                return token.text

            case 'strong':
            case 'em':
            case 'del':
                return token.tokens ? token.tokens.map(extractText).join('') : ''

            case 'link': {
                const linkText = token.tokens ? token.tokens.map(extractText).join('') : token.text || ''
                const href = resolveUrl(token.href)
                return linkText && href ? `${linkText} (${href})` : linkText || href || ''
            }

            case 'image':
                return token.tokens ? token.tokens.map(extractText).join('') : token.text || ''

            case 'br':
                return '\n'

            case 'space':
                return ''

            case 'hr':
                return '---'

            case 'html':
                return ''

            case 'table':
                // Extract text from table rows and cells
                const headerText = token.header.map((cell: any) => cell.tokens.map(extractText).join('')).join(' | ')
                const rowsText = token.rows
                    .map((row: any) => row.map((cell: any) => cell.tokens.map(extractText).join('')).join(' | '))
                    .join('\n')
                return headerText + '\n' + rowsText

            default:
                // For any unhandled token types, try to extract text if available
                if ('text' in token && typeof token.text === 'string') {
                    return token.text
                }
                if ('tokens' in token && Array.isArray(token.tokens)) {
                    return token.tokens.map(extractText).join('')
                }
                return ''
        }
    }

    // Extract text from all tokens and join with double newlines between blocks
    const result = tokens.map(extractText).join('\n\n')

    // Replace multiple consecutive newlines (3+) with just 2 to preserve paragraph breaks
    return result.replace(/\n{3,}/g, '\n\n').trim()
}

/** A TipTap doc holding a single empty paragraph — the canonical "no content" value. */
export const EMPTY_TIPTAP_DOC: JSONContent = {
    type: 'doc',
    content: [{ type: 'paragraph' }],
}

/** True when a TipTap doc contains nothing but empty paragraph(s), so it should be treated as blank. */
export function isEffectivelyEmptyTiptapDoc(doc: JSONContent): boolean {
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

/**
 * Parse markdown into a TipTap doc using the given manager, expanding flattened tables first.
 * Falls back to a single plain-text paragraph if the markdown is malformed or doesn't parse to a doc.
 */
export function markdownToTiptapDoc(manager: MarkdownManager, markdown: string | null | undefined): JSONContent {
    if (!markdown || markdown.trim() === '') {
        return EMPTY_TIPTAP_DOC
    }

    try {
        const parsed = manager.parse(expandFlattenedMarkdownTables(markdown)) as JSONContent
        if (parsed.type === 'doc') {
            return parsed
        }
    } catch {
        // Fall through to plain paragraph fallback for malformed markdown.
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

/** Serialize a TipTap doc to markdown using the given manager. Empty docs and failures yield ''. */
export function tiptapDocToMarkdown(manager: MarkdownManager, doc: JSONContent): string {
    try {
        if (isEffectivelyEmptyTiptapDoc(doc)) {
            return ''
        }

        return manager.serialize(doc).trimEnd()
    } catch {
        return ''
    }
}

/** True when markdown survives a parse -> serialize -> parse round trip unchanged (i.e. the editor won't mangle it). */
export function isTiptapMarkdownRoundTripSafe(manager: MarkdownManager, markdown: string | null | undefined): boolean {
    if (!markdown || markdown.trim() === '') {
        return true
    }

    try {
        const expanded = expandFlattenedMarkdownTables(markdown)
        const originalDoc = manager.parse(expanded) as JSONContent
        const roundTripDoc = manager.parse(manager.serialize(originalDoc).trimEnd()) as JSONContent
        return JSON.stringify(originalDoc) === JSON.stringify(roundTripDoc)
    } catch {
        return false
    }
}

export type TiptapMarkdownConverter = {
    markdownToDoc: (markdown: string | null | undefined) => JSONContent
    docToMarkdown: (doc: JSONContent) => string
    isRoundTripSafe: (markdown: string | null | undefined) => boolean
}

/**
 * Build a markdown <-> TipTap doc converter bound to a set of extensions. Each editor (text card,
 * AI prompt, etc.) supplies its own extensions but shares the parse/serialize/empty/round-trip logic.
 */
export function createTiptapMarkdownConverter(extensions: Extensions): TiptapMarkdownConverter {
    const manager = new MarkdownManager({ extensions })
    return {
        markdownToDoc: (markdown) => markdownToTiptapDoc(manager, markdown),
        docToMarkdown: (doc) => tiptapDocToMarkdown(manager, doc),
        isRoundTripSafe: (markdown) => isTiptapMarkdownRoundTripSafe(manager, markdown),
    }
}

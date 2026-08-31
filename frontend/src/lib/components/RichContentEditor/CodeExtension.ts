import { JSONContent } from '@tiptap/core'
import { Code } from '@tiptap/extension-code'
import { isAllowedUri } from '@tiptap/extension-link'
import { Lexer } from 'marked'

/**
 * `@tiptap/extension-code` parses a code span to one plain text node, so a link written inside one
 * — `` `[label](url)` `` — keeps its brackets and parens as visible punctuation instead of becoming
 * clickable. Authors write that shape when they document a table or a schema on a dashboard card.
 *
 * Lex the span's own text and keep the links, so the span reads as code and its links still work.
 */

/**
 * Only a link the author wrote as `[label](url)` is worth recovering. Everything else stays
 * literal, which keeps `*` and `_` intact in code, and leaves a bare URL alone — a code span can
 * sit inside a link already, and linking its text again would nest one link inside another.
 */
function codeSpanContent(text: string): JSONContent[] {
    const nodes: JSONContent[] = []
    let literal = ''

    const flushLiteral = (): void => {
        if (literal) {
            nodes.push({ type: 'text', text: literal })
            literal = ''
        }
    }

    for (const token of Lexer.lexInline(text)) {
        // A link mark blanks a href it will not render, so a refused scheme stays literal punctuation
        // rather than becoming an empty link.
        if (token.type === 'link' && token.raw.startsWith('[') && isAllowedUri(token.href)) {
            flushLiteral()
            nodes.push({
                type: 'text',
                text: token.text,
                marks: [{ type: 'link', attrs: { href: token.href, title: token.title || null } }],
            })
        } else {
            literal += token.raw
        }
    }
    flushLiteral()

    return nodes.length ? nodes : [{ type: 'text', text }]
}

export const CodeExtension = Code.extend({
    parseMarkdown: (token, helpers) => helpers.applyMark('code', codeSpanContent(token.text || '')),
})

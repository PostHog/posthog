import { DomNode, compile } from 'html-to-text'

const SKIPPED_SELECTORS = [
    'head',
    'script',
    'style',
    'title',
    'noscript',
    'template',
    '[hidden]',
    // The two spellings email builders write. Selectors match style text literally, so rarer spacing is not covered.
    '[style*="display:none" i]',
    '[style*="display: none" i]',
]

// Bounds the work per send. Longer html goes out without a text part, as html-only emails always did.
const MAX_HTML_CHARACTERS = 1 << 20

const HEADINGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']

const VISIBLE_CHARACTER = /[^\s\p{Cf}\p{M}]/u
// Soft hyphens, zero-width spaces, word joiners and byte order marks can sit inside a code like 482&shy;913
// without showing, so a code copied from the text part would differ from the one the html shows.
const INVISIBLE_SEPARATORS = /[\u00ad\u200b\u2060\ufeff]/g

const LIST_TAGS = new Set(['ul', 'ol'])

const SCRIPT_URL = /^javascript:/i

const linkTarget = (path: string): string => {
    const target = path.trim()
    return SCRIPT_URL.test(target) || target.startsWith('#') ? '' : target
}

const hasReadableContent = (node: DomNode): boolean =>
    node.type === 'text'
        ? VISIBLE_CHARACTER.test(node.data ?? '')
        : node.name === 'img'
          ? Boolean(node.attribs?.alt?.trim())
          : (node.name === 'a' && Boolean(linkTarget(node.attribs?.href ?? ''))) ||
            (node.children ?? []).some(hasReadableContent)

const toText = compile({
    wordwrap: false,
    // Leaves out the zero-width space, which the library treats as whitespace, so it is dropped below instead.
    whitespaceCharacters: ' \t\r\n\f',
    // By default only the first <body> is rendered, which drops content a sender put after </body>.
    baseElements: { selectors: [], returnDomByDefault: true },
    limits: { maxInputLength: MAX_HTML_CHARACTERS },
    selectors: [
        ...SKIPPED_SELECTORS.map((selector) => ({ selector, format: 'skip' })),
        ...HEADINGS.map((selector) => ({ selector, options: { uppercase: false } })),
        {
            selector: 'a',
            options: { hideLinkHrefIfSameAsText: true, linkBrackets: ['(', ')'], pathRewrite: linkTarget },
        },
        // The library indents nested lists and quotes once per level, which can grow the text far past the html.
        // Flat blocks keep the text about the size of the html.
        { selector: 'blockquote', format: 'block' },
        { selector: 'ul', format: 'block', options: { leadingLineBreaks: 2, trailingLineBreaks: 2 } },
        { selector: 'ol', format: 'block', options: { leadingLineBreaks: 2, trailingLineBreaks: 2 } },
        { selector: 'li', format: 'listItem' },
        { selector: 'img', format: 'altText' },
        { selector: 'table', format: 'block' },
        { selector: 'tr', format: 'block' },
        { selector: 'td', format: 'block', options: { leadingLineBreaks: 1, trailingLineBreaks: 1 } },
        { selector: 'th', format: 'block', options: { leadingLineBreaks: 1, trailingLineBreaks: 1 } },
    ],
    formatters: {
        listItem: (elem, walk, builder) => {
            const first = elem.children.find(hasReadableContent)
            if (!first) {
                return
            }
            builder.openBlock({ leadingLineBreaks: 1 })
            // An item that opens with a nested list gets no marker of its own.
            if (!first.name || !LIST_TAGS.has(first.name)) {
                builder.addInline('- ')
            }
            walk(elem.children, builder)
            builder.closeBlock({ trailingLineBreaks: 1 })
        },
        altText: (elem, _walk, builder) => {
            const alt = elem.attribs?.alt?.trim()
            if (alt) {
                builder.addInline(alt)
            }
        },
    },
})

export const plainTextFromHtml = (html: string): string => {
    if (html.length > MAX_HTML_CHARACTERS) {
        return ''
    }
    let text: string
    try {
        text = toText(html).replace(INVISIBLE_SEPARATORS, '').trim()
    } catch {
        // html-to-text recurses once per element, so deeply nested html overflows the stack.
        // The email then goes out without a text part, as html-only emails always did.
        return ''
    }
    return VISIBLE_CHARACTER.test(text) ? text : ''
}

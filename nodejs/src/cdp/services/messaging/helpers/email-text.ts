import { DomNode, compile } from 'html-to-text'

const SKIPPED_SELECTORS = [
    'head',
    'script',
    'style',
    'title',
    'noscript',
    'template',
    '[hidden]',
    '[style*="display:none" i]',
]

// Selectors match style text literally, so spacing in "display : none" is removed inside tags before matching.
const TAG = /<[a-z][^>]*>/gi
const STYLE_ATTRIBUTE = /\bstyle\s*=\s*("[^"]*"|'[^']*')/gi
const HIDING_DISPLAY = /display\s*:\s*none/gi

// Bounds the work per send. Longer html goes out without a text part, as html-only emails always did.
const MAX_HTML_CHARACTERS = 1 << 20

const HEADINGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']

const VISIBLE_CHARACTER = /[^\s\p{Cf}\p{M}]/u
const ZERO_WIDTH_SPACE = /\u200b/g
// An item whose content starts with a block leaves its marker on a line of its own.
const LONE_LIST_MARKER = /^-\n+/gm

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
          : (node.children ?? []).some(hasReadableContent)

const toText = compile({
    wordwrap: false,
    // Zero-width spaces split codes such as 482&#8203;913; they are dropped below instead of becoming spaces.
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
            if (!hasReadableContent(elem)) {
                return
            }
            builder.openBlock({ leadingLineBreaks: 1 })
            builder.addInline('- ')
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

const withPlainHidingStyles = (html: string): string =>
    html.replace(TAG, (tag) =>
        tag.replace(STYLE_ATTRIBUTE, (attribute) => attribute.replace(HIDING_DISPLAY, 'display:none'))
    )

export const plainTextFromHtml = (html: string): string => {
    if (html.length > MAX_HTML_CHARACTERS) {
        return ''
    }
    let text: string
    try {
        text = toText(withPlainHidingStyles(html)).replace(ZERO_WIDTH_SPACE, '').replace(LONE_LIST_MARKER, '').trim()
    } catch {
        // html-to-text recurses once per element, so deeply nested html overflows the stack.
        // The email then goes out without a text part, as html-only emails always did.
        return ''
    }
    return VISIBLE_CHARACTER.test(text) ? text : ''
}

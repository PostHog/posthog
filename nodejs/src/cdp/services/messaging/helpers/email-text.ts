import { compile } from 'html-to-text'

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

// Selectors match style text literally, so spacing in "display : none" is removed before matching.
const STYLE_ATTRIBUTE = /\bstyle\s*=\s*("[^"]*"|'[^']*')/gi
const HIDING_DISPLAY = /display\s*:\s*none/gi

// The library cuts longer input short, and a text part missing its end is worse than none.
const MAX_HTML_LENGTH = 1 << 24

const HEADINGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']

// The hyphen is the list item prefix, so a list of image-only items still counts as empty.
const VISIBLE_CHARACTER = /[^\s\p{Cf}\p{M}-]/u

const SCRIPT_URL = /^\s*javascript:/i

const toText = compile({
    wordwrap: false,
    // By default only the first <body> is rendered, which drops content a sender put after </body>.
    baseElements: { selectors: [], returnDomByDefault: true },
    limits: { maxInputLength: MAX_HTML_LENGTH },
    selectors: [
        ...SKIPPED_SELECTORS.map((selector) => ({ selector, format: 'skip' })),
        ...HEADINGS.map((selector) => ({ selector, options: { uppercase: false } })),
        {
            selector: 'a',
            options: {
                hideLinkHrefIfSameAsText: true,
                linkBrackets: ['(', ')'],
                pathRewrite: (path: string) => (SCRIPT_URL.test(path) ? '' : path),
            },
        },
        // The default prefixes each line with "> " per level, so nested quotes multiply the text's size.
        { selector: 'blockquote', format: 'block' },
        { selector: 'img', format: 'altText' },
        { selector: 'ul', options: { itemPrefix: '- ' } },
        { selector: 'table', format: 'block' },
        { selector: 'tr', format: 'block' },
        { selector: 'td', format: 'block', options: { leadingLineBreaks: 1, trailingLineBreaks: 1 } },
        { selector: 'th', format: 'block', options: { leadingLineBreaks: 1, trailingLineBreaks: 1 } },
    ],
    formatters: {
        altText: (elem, _walk, builder) => {
            const alt = elem.attribs?.alt?.trim()
            if (alt) {
                builder.addInline(alt)
            }
        },
    },
})

const withPlainHidingStyles = (html: string): string =>
    html.replace(STYLE_ATTRIBUTE, (attribute) => attribute.replace(HIDING_DISPLAY, 'display:none'))

export const plainTextFromHtml = (html: string): string => {
    if (html.length > MAX_HTML_LENGTH) {
        return ''
    }
    let text: string
    try {
        text = toText(withPlainHidingStyles(html)).trim()
    } catch {
        // html-to-text recurses once per element, so deeply nested html overflows the stack.
        // The email then goes out without a text part, as html-only emails always did.
        return ''
    }
    return VISIBLE_CHARACTER.test(text) ? text : ''
}

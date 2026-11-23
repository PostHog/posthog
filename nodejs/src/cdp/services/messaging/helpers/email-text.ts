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

// List items are indented once per level, so the text can grow far past the html. These bounds keep the work
// per send small; past them the email goes out without a text part, as html-only emails always did.
const MAX_HTML_LENGTH = 1 << 20
const MAX_DEPTH = 64
// Private use character the library writes in place of content deeper than MAX_DEPTH.
const TOO_DEEP = '\uE000'

const HEADINGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']

const VISIBLE_CHARACTER = /[^\s\p{Cf}\p{M}]/u
// A list of image-only items leaves only its markers, which carry nothing to read.
const BARE_LIST_MARKER = /^[ \t]*(?:-|\d+\.)[ \t]*$/gm

const SCRIPT_URL = /^javascript:/i

const linkTarget = (path: string): string => {
    const target = path.trim()
    return SCRIPT_URL.test(target) || target.startsWith('#') ? '' : target
}

const toText = compile({
    wordwrap: false,
    // By default only the first <body> is rendered, which drops content a sender put after </body>.
    baseElements: { selectors: [], returnDomByDefault: true },
    limits: { maxInputLength: MAX_HTML_LENGTH, maxDepth: MAX_DEPTH, ellipsis: TOO_DEEP },
    selectors: [
        ...SKIPPED_SELECTORS.map((selector) => ({ selector, format: 'skip' })),
        ...HEADINGS.map((selector) => ({ selector, options: { uppercase: false } })),
        {
            selector: 'a',
            options: {
                hideLinkHrefIfSameAsText: true,
                linkBrackets: ['(', ')'],
                pathRewrite: linkTarget,
            },
        },
        // The default prefixes each line with "> " per level, so nested quotes multiply the text's size.
        { selector: 'blockquote', format: 'block' },
        { selector: 'img', format: 'altText' },
        { selector: 'ul', options: { itemPrefix: '- ' } },
        { selector: 'ol', format: 'decimalList' },
        { selector: 'table', format: 'block' },
        { selector: 'tr', format: 'block' },
        { selector: 'td', format: 'block', options: { leadingLineBreaks: 1, trailingLineBreaks: 1 } },
        { selector: 'th', format: 'block', options: { leadingLineBreaks: 1, trailingLineBreaks: 1 } },
    ],
    formatters: {
        // The library's Roman numerals throw past 3999, so ordered lists always count in decimal.
        decimalList: (elem, walk, builder, formatOptions) => {
            delete elem.attribs?.type
            builder.options.formatters?.orderedList?.(elem, walk, builder, formatOptions)
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
    html.replace(STYLE_ATTRIBUTE, (attribute) => attribute.replace(HIDING_DISPLAY, 'display:none'))

export const plainTextFromHtml = (html: string): string => {
    if (html.length > MAX_HTML_LENGTH) {
        return ''
    }
    let text: string
    try {
        text = toText(withPlainHidingStyles(html)).trim()
    } catch {
        // A converter error must not fail the send, so the email goes out without a text part.
        return ''
    }
    if (text.includes(TOO_DEEP)) {
        return ''
    }
    return VISIBLE_CHARACTER.test(text.replace(BARE_LIST_MARKER, '')) ? text : ''
}

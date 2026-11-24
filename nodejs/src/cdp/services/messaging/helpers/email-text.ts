import { compile } from 'html-to-text'

// Bounds the work per send. Longer html goes out without a text part, as html-only emails always did.
const MAX_HTML_CHARACTERS = 1 << 18

const HEADINGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']

const toText = compile({
    wordwrap: false,
    selectors: [
        { selector: 'img', format: 'skip' },
        { selector: '[hidden]', format: 'skip' },
        // The spellings email builders use to hide preheaders. Other CSS that hides text is not detected.
        { selector: '[style*="display:none" i]', format: 'skip' },
        { selector: '[style*="display: none" i]', format: 'skip' },
        ...HEADINGS.map((selector) => ({ selector, options: { uppercase: false } })),
        { selector: 'a', options: { hideLinkHrefIfSameAsText: true, linkBrackets: ['(', ')'] } },
        // Email layouts are tables, and the library would run the text of neighbouring cells together.
        { selector: 'tr', format: 'block' },
        { selector: 'td', format: 'block', options: { leadingLineBreaks: 1, trailingLineBreaks: 1 } },
        { selector: 'th', format: 'block', options: { leadingLineBreaks: 1, trailingLineBreaks: 1 } },
    ],
})

export const plainTextFromHtml = (html: string): string => {
    if (html.length > MAX_HTML_CHARACTERS) {
        return ''
    }
    try {
        const text = toText(html).trim()
        // Some markup, such as a run of <hr> tags, renders longer than its html. That text is left out.
        return text.length <= html.length ? text : ''
    } catch {
        // The library recurses once per element, so deeply nested html overflows the stack.
        // The email then goes out without a text part, as html-only emails always did.
        return ''
    }
}

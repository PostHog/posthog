import { compile } from 'html-to-text'

// Bounds the work per send. Longer html goes out without a text part, as html-only emails always did.
const MAX_HTML_CHARACTERS = 1 << 18

const HEADINGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']
// Blocks the library would render inline, running a label into the code beside it.
const UNKNOWN_BLOCKS = ['center', 'dl', 'dt', 'dd', 'figure', 'figcaption', 'address', 'details', 'summary', 'fieldset']

const toText = compile({
    wordwrap: false,
    // The library counts a zero-width space as whitespace, which would split a code or a link target.
    whitespaceCharacters: ' \t\r\n\f',
    selectors: [
        { selector: 'img', format: 'skip' },
        { selector: '[hidden]', format: 'skip' },
        // The spellings email builders use to hide preheaders. Other CSS that hides text is not detected.
        { selector: '[style*="display:none" i]', format: 'skip' },
        { selector: '[style*="display: none" i]', format: 'skip' },
        ...HEADINGS.map((selector) => ({ selector, options: { uppercase: false } })),
        ...UNKNOWN_BLOCKS.map((selector) => ({ selector, format: 'block' })),
        // The library's 40-character line would make a short email longer than its html, and drop its text part.
        { selector: 'hr', options: { length: 3 } },
        // The library indents quotes and lists by rebuilding every line at each level of nesting,
        // so deeply nested ones cost seconds. As plain blocks they cost one pass.
        ...['blockquote', 'ul', 'ol'].map((selector) => ({ selector, format: 'block' })),
        { selector: 'li', format: 'block', options: { leadingLineBreaks: 1, trailingLineBreaks: 1 } },
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

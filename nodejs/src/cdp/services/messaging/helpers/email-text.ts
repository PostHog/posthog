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
    '[style*="display: none" i]',
]

const HEADINGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']

const CONTENT_CHARACTER = /[\p{L}\p{N}\p{S}]/u

const toText = compile({
    wordwrap: false,
    selectors: [
        ...SKIPPED_SELECTORS.map((selector) => ({ selector, format: 'skip' })),
        ...HEADINGS.map((selector) => ({ selector, options: { uppercase: false } })),
        { selector: 'a', options: { hideLinkHrefIfSameAsText: true, linkBrackets: ['(', ')'] } },
        { selector: 'a[href^="javascript:" i]', format: 'inline' },
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

export const plainTextFromHtml = (html: string): string => {
    const text = toText(html).trim()
    return CONTENT_CHARACTER.test(text) ? text : ''
}

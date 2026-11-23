import { DomNode, compile } from 'html-to-text'

const SKIPPED_TAGS = new Set(['head', 'script', 'style', 'title', 'noscript', 'template'])

const DISPLAY_DECLARATION = /^display\s*:\s*([a-z-]+)(\s*!\s*important)?$/i

// A scan with indexOf, since the usual comment regex turns quadratic on many unclosed comments.
const withoutComments = (style: string): string => {
    let result = ''
    let position = 0
    for (;;) {
        const start = style.indexOf('/*', position)
        if (start < 0) {
            return result + style.slice(position)
        }
        result += style.slice(position, start)
        const end = style.indexOf('*/', start + 2)
        if (end < 0) {
            return result
        }
        position = end + 2
    }
}

// Follows the cascade within one style attribute: the last display declaration wins, unless an earlier one is important.
const isHiddenStyle = (style: string): boolean => {
    let display = ''
    let important = false
    for (const declaration of withoutComments(style).split(';')) {
        const match = DISPLAY_DECLARATION.exec(declaration.trim())
        if (match && (match[2] || !important)) {
            display = match[1].toLowerCase()
            important = Boolean(match[2])
        }
    }
    return display === 'none'
}

// Bounds the work per send. Longer html goes out without a text part, as html-only emails always did.
const MAX_HTML_CHARACTERS = 1 << 20

const HEADINGS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']
// Block elements the library renders inline, which would run the text of neighbouring blocks together.
const EXTRA_BLOCKS = ['address', 'caption', 'center', 'dd', 'details', 'dl', 'dt', 'fieldset', 'figcaption', 'figure']

const VISIBLE_CHARACTER = /[^\s\p{Cf}\p{M}]/u
// Soft hyphens, joiners, zero-width spaces, invisible operators and byte order marks can sit inside a code like 482&shy;913
// without showing, so a code copied from the text part would differ from the one the html shows.
const INVISIBLE_SEPARATORS = /[\u00ad\u034f\u200b\u2060-\u2064\ufeff]/g

const LIST_TAGS = new Set(['ul', 'ol'])

const SCRIPT_URL = /^javascript:/i

const linkTarget = (path: string): string => {
    const target = path.trim()
    if (SCRIPT_URL.test(target) || target.startsWith('#')) {
        return ''
    }
    // Encoded as a browser would send them, so the cleanup of the text leaves the link intact.
    return target.replace(INVISIBLE_SEPARATORS, encodeURIComponent)
}

const isReadable = (node: DomNode): boolean => {
    if (node.type === 'text') {
        return VISIBLE_CHARACTER.test(node.data ?? '')
    }
    const attribs = node.attribs ?? {}
    if (SKIPPED_TAGS.has(node.name ?? '') || 'hidden' in attribs || isHiddenStyle(attribs.style ?? '')) {
        return false
    }
    if (node.name === 'img') {
        return Boolean(attribs.alt?.trim())
    }
    return (
        (node.name === 'a' && Boolean(linkTarget(attribs.href ?? ''))) || (node.children ?? []).some(hasReadableContent)
    )
}

// Nested list items ask about the same descendants, so each node is answered once.
const readable = new WeakMap<DomNode, boolean>()
const hasReadableContent = (node: DomNode): boolean => {
    let result = readable.get(node)
    if (result === undefined) {
        result = isReadable(node)
        readable.set(node, result)
    }
    return result
}

const toText = compile({
    wordwrap: false,
    // Leaves out the zero-width space, which the library treats as whitespace, so it is dropped below instead.
    whitespaceCharacters: ' \t\r\n\f',
    // By default only the first <body> is rendered, which drops content a sender put after </body>.
    baseElements: { selectors: [], returnDomByDefault: true },
    limits: { maxInputLength: MAX_HTML_CHARACTERS },
    selectors: [
        ...[...SKIPPED_TAGS, '[hidden]'].map((selector) => ({ selector, format: 'skip' })),
        { selector: '[style]', format: 'styled' },
        ...HEADINGS.map((selector) => ({ selector, options: { uppercase: false } })),
        ...EXTRA_BLOCKS.map((selector) => ({
            selector,
            format: 'block',
            options: { leadingLineBreaks: 1, trailingLineBreaks: 1 },
        })),
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
        // Selectors match style text literally, so hidden styles are read from the parsed, decoded attribute here.
        // A visible element loses its style and is walked again, which renders it with its own formatter.
        styled: (elem, walk, builder) => {
            const { style, ...attribs } = elem.attribs
            if (isHiddenStyle(style)) {
                return
            }
            elem.attribs = attribs
            walk([elem], builder)
        },
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

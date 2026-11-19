import { QuoteType, Tokenizer } from 'htmlparser2'

import { escapeHtml } from './escape-html'

export type AnchorAttribute = {
    // As a browser reads it, with character references decoded. Empty for an attribute written without `=`.
    value: string
}

export type HrefAnchor = {
    href: string
    // A browser keeps the first of two same-named attributes, so this returns the first.
    attribute: (name: string) => AnchorAttribute | undefined
}

// Sets the first attribute called `name`, or adds it when the tag has none. A `null` value writes the bare name.
export type AnchorEdit = {
    name: string
    value: string | null
}

type ScannedAttribute = {
    name: string
    rawName: string
    value: string
    hasValue: boolean
    quoted: boolean
    start: number
    // Where the value starts in the source, after any opening quote.
    valueStart: number
    end: number
}

type ScannedTag = {
    attributes: ScannedAttribute[]
    // Where an added attribute goes: the `>`, or the `/` of a self-closing `/>`.
    insertAt: number
}

type Scan = {
    anchors: ScannedTag[]
    // The `<` of the first `</body>` end tag outside comments, or -1.
    bodyEnd: number
}

const JAVASCRIPT_SCHEME = /^javascript:/i

const isSpace = (char: string): boolean =>
    char === ' ' || char === '\t' || char === '\n' || char === '\f' || char === '\r'

// HTML folds only ASCII letters in names. `toLowerCase` would also fold the Kelvin sign into `k`.
const asciiLowercase = (text: string): string => text.replace(/[A-Z]/g, (char) => char.toLowerCase())

const noop = (): void => {}

// The tokenizer misreads three short forms a browser reads: it runs a comment past `--!>`, and it runs `<!>` and
// `<!->` on to the next `>`. Each rewrite keeps the length and adds no space or `>`, so offsets still point into
// `html` and no attribute boundary moves. `--->` can close a comment a browser keeps open, as in `<!--!>`, which
// only scans more markup. Inside a comment, `<!--` is text.
const BROWSER_ONLY_ENDINGS = /--!>|<!-?>/g

const alignWithBrowser = (markup: string, inComment: boolean): string => {
    const aligned = markup.replace(BROWSER_ONLY_ENDINGS, (ending) =>
        ending === '--!>' ? '--->' : `<?${ending.slice(2)}`
    )
    return inComment ? aligned.replaceAll('<!--', '_!--') : aligned
}

// A browser reads these elements' content as text up to their end tag, which a `/` may also end, as in
// `</style/>`. The tokenizer reads only some of them that way, so the scan skips to the end tag itself.
const RAW_TEXT_ELEMENTS = new Set(['iframe', 'noembed', 'noframes', 'script', 'style', 'textarea', 'title', 'xmp'])
const rawTextEndTags = new Map<string, RegExp>()

const rawTextEnd = (markup: string, name: string, from: number): number => {
    let endTag = rawTextEndTags.get(name)
    if (!endTag) {
        endTag = new RegExp(`</${name}(?=[\\t\\n\\f\\r />])`, 'gi')
        rawTextEndTags.set(name, endTag)
    }
    endTag.lastIndex = from
    return endTag.exec(markup)?.index ?? markup.length
}

// Collects the opening `<a>` tags of `html[from, to)` in document order. Comment content is scanned as markup
// too, because Outlook renders the links inside its `<!--[if mso]>` blocks. That scan reads a `<!--` as text, so
// each character is scanned at most twice however many comments a comment opens.
const scanAnchorTags = (html: string, from: number, to: number, scan: Scan, inComment = false): void => {
    const markup = alignWithBrowser(html.slice(from, to), inComment)
    let resumeAt = 0
    while (resumeAt < markup.length) {
        resumeAt = scanUntilRawText(html, from, markup, resumeAt, scan, inComment)
    }
}

const scanHtml = (html: string): Scan => {
    const scan: Scan = { anchors: [], bodyEnd: -1 }
    scanAnchorTags(html, 0, html.length, scan)
    return scan
}

// Scans `markup` from `start` and returns where to go on: past the next raw-text element, or the end.
const scanUntilRawText = (
    html: string,
    from: number,
    markup: string,
    scanStart: number,
    scan: Scan,
    inComment: boolean
): number => {
    const offset = from + scanStart
    let tagName = ''
    let isAnchor = false
    let attributes: ScannedAttribute[] = []
    let attribute: ScannedAttribute | null = null
    let resumeAt = -1

    const scanInner = (start: number, end: number, endOffset: number): void => {
        if (!inComment) {
            scanAnchorTags(html, offset + start, offset + end - endOffset, scan, true)
        }
    }
    const closeTag = (insertAt: number): void => {
        if (isAnchor) {
            scan.anchors.push({ attributes, insertAt })
        }
        isAnchor = false
    }

    const tokenizer = new Tokenizer(
        { decodeEntities: true },
        {
            onopentagname(start, end) {
                tagName = asciiLowercase(html.slice(offset + start, offset + end))
                isAnchor = tagName === 'a'
                attributes = []
            },
            onattribname(start, end) {
                const rawName = html.slice(offset + start, offset + end)
                attribute = {
                    name: asciiLowercase(rawName),
                    rawName,
                    value: '',
                    hasValue: false,
                    quoted: false,
                    start: offset + start,
                    valueStart: offset + end,
                    end: offset + end,
                }
            },
            onattribdata(start, end) {
                attribute!.value += html.slice(offset + start, offset + end)
            },
            onattribentity(codepoint) {
                attribute!.value += String.fromCodePoint(codepoint)
            },
            onattribend(quote, end) {
                attribute!.hasValue = quote !== QuoteType.NoValue
                attribute!.quoted = quote === QuoteType.Single || quote === QuoteType.Double
                if (attribute!.hasValue) {
                    let valueStart = html.indexOf('=', attribute!.end) + 1
                    while (isSpace(html[valueStart])) {
                        valueStart++
                    }
                    attribute!.valueStart = attribute!.quoted ? valueStart + 1 : valueStart
                }
                attribute!.end = offset + end
                attributes.push(attribute!)
                attribute = null
            },
            onopentagend(end) {
                closeTag(offset + end)
                if (tagName === 'plaintext') {
                    resumeAt = markup.length
                } else if (RAW_TEXT_ELEMENTS.has(tagName)) {
                    resumeAt = rawTextEnd(markup, tagName, scanStart + end + 1)
                }
                if (resumeAt >= 0) {
                    tokenizer.pause()
                }
            },
            onselfclosingtag(end) {
                let slash = offset + end - 1
                while (isSpace(html[slash])) {
                    slash--
                }
                closeTag(slash)
            },
            oncomment: scanInner,
            oncdata: scanInner,
            onclosetag(start, end) {
                // The tokenizer skips spaces after `</`, where a browser reads a comment instead.
                const tagStart = offset + start - 2
                const isBodyEnd =
                    !inComment &&
                    scan.bodyEnd < 0 &&
                    html.startsWith('</', tagStart) &&
                    asciiLowercase(html.slice(offset + start, offset + end)) === 'body'
                if (isBodyEnd) {
                    scan.bodyEnd = tagStart
                }
            },
            ondeclaration: noop,
            onend: noop,
            onprocessinginstruction: noop,
            ontext: noop,
            ontextentity: noop,
        }
    )
    tokenizer.write(markup.slice(scanStart))
    if (resumeAt >= 0) {
        return resumeAt
    }
    tokenizer.end()
    return markup.length
}

const firstByName = (attributes: ScannedAttribute[]): Map<string, ScannedAttribute> => {
    const first = new Map<string, ScannedAttribute>()
    for (const attribute of attributes) {
        if (!first.has(attribute.name)) {
            first.set(attribute.name, attribute)
        }
    }
    return first
}

// Calls `edit` for each anchor with a usable href, in document order, and applies the edit it returns to the
// opening tag. The rest of the email stays byte for byte as written.
export const editHrefAnchors = (html: string, edit: (anchor: HrefAnchor) => AnchorEdit | null): string => {
    const tags = scanHtml(html).anchors

    const pieces: string[] = []
    let copiedUpTo = 0
    for (const tag of tags) {
        const attributes = firstByName(tag.attributes)
        const href = attributes.get('href')
        if (!href || !href.hasValue || (!href.quoted && href.value === '')) {
            continue
        }
        // Read on the source text, not the decoded value, so an encoded scheme still counts as a link, as it always has.
        if (JAVASCRIPT_SCHEME.test(html.slice(href.valueStart, href.valueStart + 'javascript:'.length))) {
            continue
        }
        const change = edit({ href: href.value, attribute: (name) => attributes.get(name) })
        if (!change) {
            continue
        }
        const existing = attributes.get(change.name)
        const name = existing?.rawName ?? change.name
        // `<` and `>` are escaped too: a raw `-->` would end an Outlook conditional comment around the link.
        const written = change.value === null ? name : `${name}="${escapeHtml(change.value)}"`

        if (existing) {
            pieces.push(html.slice(copiedUpTo, existing.start), written)
            copiedUpTo = existing.end
            continue
        }
        const last = tag.attributes[tag.attributes.length - 1]
        if (last?.hasValue && !last.quoted && last.value === '') {
            // `title=>` followed by ` name` would make `name` the value of `title`, so the empty value gets quotes.
            pieces.push(html.slice(copiedUpTo, last.start), `${last.rawName}="" ${written}`)
        } else {
            // A loop, not /\s+$/, which backtracks quadratically over a long run of spaces inside the tag.
            let before = tag.insertAt
            while (before > 0 && isSpace(html[before - 1])) {
                before--
            }
            pieces.push(html.slice(copiedUpTo, before), ` ${written}`)
        }
        // From the `/` of a self-closing `/>`, which closes an SVG link.
        copiedUpTo = tag.insertAt
    }
    pieces.push(html.slice(copiedUpTo))
    return pieces.join('')
}

// Inserts `markup` before the body end tag a browser reads, not a `</body>` inside an attribute or a comment. An
// email without one is returned as written.
export const insertBeforeBodyEnd = (html: string, markup: string): string => {
    const { bodyEnd } = scanHtml(html)
    return bodyEnd < 0 ? html : html.slice(0, bodyEnd) + markup + html.slice(bodyEnd)
}

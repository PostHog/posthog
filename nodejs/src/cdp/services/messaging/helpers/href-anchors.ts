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

const JAVASCRIPT_SCHEME = /^javascript:/i

const isSpace = (char: string): boolean =>
    char === ' ' || char === '\t' || char === '\n' || char === '\f' || char === '\r'

// HTML folds only ASCII letters in names. `toLowerCase` would also fold the Kelvin sign into `k`.
const asciiLowercase = (text: string): string => text.replace(/[A-Z]/g, (char) => char.toLowerCase())

const noop = (): void => {}

// A browser ends a comment at `--!>` and a raw-text element at `</style/`, where the tokenizer does not.
const BROWSER_ONLY_ENDINGS = /--!>|<\/(?:script|style|textarea|title)\//gi

// Rewrites that keep the length, so every offset still points into `html`. Inside a comment, `<!--` is text.
const alignWithBrowser = (markup: string, inComment: boolean): string => {
    const aligned = markup.replace(BROWSER_ONLY_ENDINGS, (ending) =>
        ending === '--!>' ? ' -->' : `${ending.slice(0, -1)} `
    )
    return inComment ? aligned.replaceAll('<!--', '_!--') : aligned
}

// Collects the opening `<a>` tags of `html[from, to)` in document order. Comment content is scanned as markup
// too, because Outlook renders the links inside its `<!--[if mso]>` blocks. That scan reads a `<!--` as text, so
// each character is scanned at most twice however many comments a comment opens.
const scanAnchorTags = (html: string, from: number, to: number, found: ScannedTag[], inComment = false): void => {
    let isAnchor = false
    let attributes: ScannedAttribute[] = []
    let attribute: ScannedAttribute | null = null

    const scanInner = (start: number, end: number, endOffset: number): void => {
        if (!inComment) {
            scanAnchorTags(html, from + start, from + end - endOffset, found, true)
        }
    }
    const closeTag = (insertAt: number): void => {
        if (isAnchor) {
            found.push({ attributes, insertAt })
        }
        isAnchor = false
    }

    const tokenizer = new Tokenizer(
        { decodeEntities: true },
        {
            onopentagname(start, end) {
                isAnchor = asciiLowercase(html.slice(from + start, from + end)) === 'a'
                attributes = []
            },
            onattribname(start, end) {
                const rawName = html.slice(from + start, from + end)
                attribute = {
                    name: asciiLowercase(rawName),
                    rawName,
                    value: '',
                    hasValue: false,
                    quoted: false,
                    start: from + start,
                    valueStart: from + end,
                    end: from + end,
                }
            },
            onattribdata(start, end) {
                attribute!.value += html.slice(from + start, from + end)
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
                attribute!.end = from + end
                attributes.push(attribute!)
                attribute = null
            },
            onopentagend(end) {
                closeTag(from + end)
            },
            onselfclosingtag(end) {
                let slash = from + end - 1
                while (isSpace(html[slash])) {
                    slash--
                }
                closeTag(slash)
            },
            oncomment: scanInner,
            oncdata: scanInner,
            onclosetag: noop,
            ondeclaration: noop,
            onend: noop,
            onprocessinginstruction: noop,
            ontext: noop,
            ontextentity: noop,
        }
    )
    tokenizer.write(alignWithBrowser(html.slice(from, to), inComment))
    tokenizer.end()
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
    const tags: ScannedTag[] = []
    scanAnchorTags(html, 0, html.length, tags)

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

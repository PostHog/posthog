import { QuoteType, Tokenizer } from 'htmlparser2'

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
    end: number
}

type ScannedTag = {
    attributes: ScannedAttribute[]
    // Where an added attribute goes: the `>`, or the `/` of a self-closing `/>`.
    insertAt: number
    // Just past the `>`.
    end: number
}

const JAVASCRIPT_SCHEME = /^javascript:/i

const isSpace = (char: string): boolean =>
    char === ' ' || char === '\t' || char === '\n' || char === '\f' || char === '\r'

// HTML folds only ASCII letters in names. `toLowerCase` would also fold the Kelvin sign into `k`.
const asciiLowercase = (text: string): string => text.replace(/[A-Z]/g, (char) => char.toLowerCase())

const escapeAttributeValue = (value: string): string => value.replaceAll('&', '&amp;').replaceAll('"', '&quot;')

const noop = (): void => {}

// Collects the opening `<a>` tags of `html[from, to)` in document order. Comment content is scanned as markup
// too, because Outlook renders the links inside its `<!--[if mso]>` blocks.
const scanAnchorTags = (html: string, from: number, to: number, found: ScannedTag[]): void => {
    let isAnchor = false
    let attributes: ScannedAttribute[] = []
    let attribute: ScannedAttribute | null = null

    const scanInner = (start: number, end: number, endOffset: number): void =>
        scanAnchorTags(html, from + start, from + end - endOffset, found)
    const closeTag = (insertAt: number, end: number): void => {
        if (isAnchor) {
            found.push({ attributes, insertAt, end })
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
                attribute!.end = from + end
                attributes.push(attribute!)
                attribute = null
            },
            onopentagend(end) {
                closeTag(from + end, from + end + 1)
            },
            onselfclosingtag(end) {
                let slash = from + end - 1
                while (isSpace(html[slash])) {
                    slash--
                }
                closeTag(slash, from + end + 1)
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
    tokenizer.write(html.slice(from, to))
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
        if (!href || !href.hasValue || (!href.quoted && href.value === '') || JAVASCRIPT_SCHEME.test(href.value)) {
            continue
        }
        const change = edit({ href: href.value, attribute: (name) => attributes.get(name) })
        if (!change) {
            continue
        }
        const written = change.value === null ? change.name : `${change.name}="${escapeAttributeValue(change.value)}"`

        const existing = attributes.get(change.name)
        if (existing) {
            pieces.push(html.slice(copiedUpTo, existing.start), written)
            copiedUpTo = existing.end
            continue
        }
        const last = tag.attributes[tag.attributes.length - 1]
        if (last?.hasValue && !last.quoted && last.value === '') {
            // `title=>` followed by ` name` would make `name` the value of `title`, so the empty value gets quotes.
            pieces.push(html.slice(copiedUpTo, last.start), `${last.rawName}="" ${written}>`)
        } else {
            // A loop, not /\s+$/, which backtracks quadratically over a long run of spaces inside the tag.
            let before = tag.insertAt
            while (before > 0 && isSpace(html[before - 1])) {
                before--
            }
            pieces.push(html.slice(copiedUpTo, before), ` ${written}>`)
        }
        copiedUpTo = tag.end
    }
    pieces.push(html.slice(copiedUpTo))
    return pieces.join('')
}

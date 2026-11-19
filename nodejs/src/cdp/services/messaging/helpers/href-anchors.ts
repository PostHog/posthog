import {
    DefaultTreeAdapterMap,
    Parser,
    Token,
    TreeAdapter,
    defaultTreeAdapter,
    parseFragment,
    html as spec,
} from 'parse5'

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
    start: number
    // The attributes a browser keeps: the first of each name.
    attributes: ScannedAttribute[]
    // The last attribute written in the tag, a dropped repeat included.
    last: SourceAttribute | undefined
    // Where an added attribute goes: the `>`, or the `/` of a self-closing `/>`.
    insertAt: number
}

type Node = DefaultTreeAdapterMap['node']
type Element = DefaultTreeAdapterMap['element']

const JAVASCRIPT_SCHEME = /^javascript:/i

const isSpace = (char: string): boolean =>
    char === ' ' || char === '\t' || char === '\n' || char === '\f' || char === '\r'

// Email clients run no scripts, so `<noscript>` content is read as markup.
const PARSE_OPTIONS = { sourceCodeLocationInfo: true, scriptingEnabled: false } as const

// A same-length stand-in for `<!--` inside a comment, where it is text. `<_` opens no tag.
const COMMENT_OPENING = '<!--'
const COMMENT_OPENING_AS_TEXT = '<_--'
// Outlook renders the content of `<!--[if mso]>` and its kin; every other comment shows nothing in any client.
const CONDITIONAL_COMMENT = /^\s*\[if\b/i

type SourceAttribute = Omit<ScannedAttribute, 'name' | 'value'>

// The parser looks back through the open elements for some tags, so its time grows with the nesting depth times the
// number of tags. The depth an email may reach shrinks as its tag count grows, so that product stays under a budget,
// down to a floor far deeper than real emails nest. That keeps the read of an email of any size linear.
export const NESTING_BUDGET = 10_000_000
export const MIN_NESTING_LIMIT = 256
// The parser copies each formatting element left open, such as `<b>` or `<font>`, into every block after it, so a
// short email can build elements with the square of its size. Allowing a few per tag keeps the tree linear.
export const ELEMENTS_PER_TAG = 2
export const MIN_ELEMENT_BUDGET = 50_000
// Each element costs memory and time even when the tree stays linear, and a send may carry tens of megabytes of
// HTML. No email a client renders in full comes near this many.
export const MAX_ELEMENT_BUDGET = 500_000
// The tokenizer builds each attribute with its source location before the parser sees the tag, so one tag can hold
// hundreds of megabytes of them.
export const MAX_ATTRIBUTE_BUDGET = 200_000
// Each word and each space between words is a run of text the tokenizer builds with its source location, and inside a
// table the parser holds every run until the table ends.
export const MAX_TEXT_RUN_BUDGET = 500_000
// The parser compares each formatting element a start tag opens with every one still open, attribute by attribute, so
// many open formatting elements with many attributes cost their count times their attributes. The copies it rebuilds
// from an earlier tag are not compared. Work on its list of formatting elements, and each read of an element's
// attributes with the length of their values, counts against the same budget.
export const FORMATTING_BUDGET = 10_000_000
const FORMATTING_TAGS = new Set([
    'a',
    'b',
    'big',
    'code',
    'em',
    'font',
    'i',
    'nobr',
    's',
    'small',
    'strike',
    'strong',
    'tt',
    'u',
])

// Shared by the document and every comment read as markup, so the elements they build together stay in budget.
type ParseBounds = {
    depth: number
    elementsLeft: number
    attributesLeft: number
    textRunsLeft: number
    formattingLeft: number
}

const parseBoundsFor = (html: string): ParseBounds => {
    let tags = 0
    for (let at = html.indexOf('<'); at >= 0; at = html.indexOf('<', at + 1)) {
        tags++
    }
    return {
        depth: Math.max(MIN_NESTING_LIMIT, Math.floor(NESTING_BUDGET / Math.max(tags, 1))),
        elementsLeft: Math.min(MAX_ELEMENT_BUDGET, MIN_ELEMENT_BUDGET + ELEMENTS_PER_TAG * tags),
        attributesLeft: MAX_ATTRIBUTE_BUDGET,
        textRunsLeft: MAX_TEXT_RUN_BUDGET,
        formattingLeft: FORMATTING_BUDGET,
    }
}

export class EmailHtmlTooComplexError extends Error {}

export class EmailNestingTooDeepError extends EmailHtmlTooComplexError {
    constructor(limit: number) {
        super(
            `This email nests HTML elements more than ${limit} levels deep, which is too deep to read its links. Remove some of the nesting and send it again.`
        )
        this.name = 'EmailNestingTooDeepError'
    }
}

export class EmailFormattingTooCostlyError extends EmailHtmlTooComplexError {
    constructor() {
        super(
            'This email has too many elements, attributes or words, or leaves formatting tags such as <b> or <font> open across too much of it, to read its links. Simplify its HTML and send it again.'
        )
        this.name = 'EmailFormattingTooCostlyError'
    }
}

type FormattingList = Parser<DefaultTreeAdapterMap>['activeFormattingElements']

// The formatting elements still open since the last table cell, caption or similar boundary, which the parser compares
// a new one with. A boundary entry holds no element.
const openFormattingCount = (list: FormattingList | undefined): number => {
    let count = 0
    while (list && count < list.entries.length && 'element' in list.entries[count]) {
        count++
    }
    return count
}

// Stops a parse that builds more elements or formatting work than the email's budget.
const boundedAdapter = (
    bounds: ParseBounds,
    formattingList: () => FormattingList | undefined
): TreeAdapter<DefaultTreeAdapterMap> => {
    const attributeNames = new WeakMap<Element, Set<string>>()
    // A rebuilt copy shares its tag's attribute list, so a list seen before marks a copy.
    const tagAttributes = new WeakSet<Element['attrs']>()
    const opened = new WeakSet<Element>()
    const readCosts = new WeakMap<Element['attrs'], number>()
    const attributeReadCost = (attrs: Element['attrs']): number => {
        let cost = readCosts.get(attrs)
        if (cost === undefined) {
            cost = attrs.reduce((sum, attr) => sum + 1 + attr.value.length, 0)
            readCosts.set(attrs, cost)
        }
        return cost
    }
    const place = (node: Node): void => {
        // A comment holds no elements, so it adds no nesting.
        if (!('attrs' in node)) {
            return
        }
        if (opened.delete(node)) {
            bounds.formattingLeft -= (openFormattingCount(formattingList()) + 1) * (node.attrs.length + 1)
            if (bounds.formattingLeft < 0) {
                throw new EmailFormattingTooCostlyError()
            }
        }
    }
    return {
        ...defaultTreeAdapter,
        // The parser rereads an element's attributes, such as a MathML annotation's for its encoding each time a
        // child opens or closes inside it, and compares their values with a new formatting tag's, so each read costs
        // the length of the values too.
        getAttrList(element) {
            bounds.formattingLeft -= attributeReadCost(element.attrs)
            if (bounds.formattingLeft < 0) {
                throw new EmailFormattingTooCostlyError()
            }
            return defaultTreeAdapter.getAttrList(element)
        },
        createElement(tagName, namespaceURI, attrs) {
            if (--bounds.elementsLeft < 0) {
                throw new EmailFormattingTooCostlyError()
            }
            const element = defaultTreeAdapter.createElement(tagName, namespaceURI, attrs)
            if (FORMATTING_TAGS.has(tagName) && !tagAttributes.has(attrs)) {
                tagAttributes.add(attrs)
                opened.add(element)
            }
            return element
        },
        appendChild(parent, node) {
            place(node)
            defaultTreeAdapter.appendChild(parent, node)
        },
        insertBefore(parent, node, reference) {
            place(node)
            defaultTreeAdapter.insertBefore(parent, node, reference)
        },
        // Each repeated `<html>` or `<body>` tag adds its new attributes to the first one. The default adapter
        // collects the names already there on every merge, which grows with the square of the input.
        adoptAttributes(recipient, attrs) {
            let names = attributeNames.get(recipient)
            if (!names) {
                names = new Set(recipient.attrs.map((attribute) => attribute.name))
                attributeNames.set(recipient, names)
            }
            for (const attribute of attrs) {
                if (!names.has(attribute.name)) {
                    names.add(attribute.name)
                    recipient.attrs.push(attribute)
                }
            }
        },
    }
}

// Stops a parse when its stack of open elements grows deeper than the limit. The stack is what the parser looks back
// through, and it can run deeper than the tree position an element was placed at: a formatting tag the parser rebuilds
// takes in children before it joins the tree.
const limitNesting = (parser: Parser<DefaultTreeAdapterMap>, bounds: ParseBounds): void => {
    const stack = parser.openElements
    const push = stack.push.bind(stack)
    stack.push = (element, tagID) => {
        push(element, tagID)
        if (stack.stackTop + 1 > bounds.depth) {
            throw new EmailNestingTooDeepError(bounds.depth)
        }
    }
}

// Charges each change to the list of formatting elements and boundaries, and each lookup that reads all of it, the
// list's length: the list adds at its front and looks entries up from there. Nesting does not bound the list, since
// a `</template>` clears it only back to the boundary an `<object>` inside added, leaving the template's own behind.
const limitFormattingListWork = (parser: Parser<DefaultTreeAdapterMap>, bounds: ParseBounds): void => {
    const list = parser.activeFormattingElements
    const charged =
        <Args extends unknown[], Result>(call: (...args: Args) => Result) =>
        (...args: Args): Result => {
            bounds.formattingLeft -= list.entries.length
            if (bounds.formattingLeft < 0) {
                throw new EmailFormattingTooCostlyError()
            }
            return call(...args)
        }
    list.insertMarker = charged(list.insertMarker.bind(list))
    list.pushElement = charged(list.pushElement.bind(list))
    list.insertElementAfterBookmark = charged(list.insertElementAfterBookmark.bind(list))
    list.removeEntry = charged(list.removeEntry.bind(list))
    list.clearToLastMarker = charged(list.clearToLastMarker.bind(list))
    list.getElementEntryInScopeWithTagName = charged(list.getElementEntryInScopeWithTagName.bind(list))
    list.getElementEntry = charged(list.getElementEntry.bind(list))
}

// Stops a parse before the tokenizer starts an attribute or a run of text past its budget, since it builds a whole
// tag's attributes before the parser sees the tag. `_createAttr` and `_createCharacterToken` are internal to the
// tokenizer of parse5 7.1.2, which the patch pins.
const limitTokens = (parser: Parser<DefaultTreeAdapterMap>, bounds: ParseBounds): void => {
    const tokenizer = parser.tokenizer as unknown as {
        _createAttr: (firstCharacter: string) => void
        _createCharacterToken: (type: unknown, chars: string) => void
    }
    const createAttr = tokenizer._createAttr.bind(tokenizer)
    tokenizer._createAttr = (firstCharacter) => {
        if (--bounds.attributesLeft < 0) {
            throw new EmailFormattingTooCostlyError()
        }
        createAttr(firstCharacter)
    }
    const createCharacterToken = tokenizer._createCharacterToken.bind(tokenizer)
    tokenizer._createCharacterToken = (type, chars) => {
        if (--bounds.textRunsLeft < 0) {
            throw new EmailFormattingTooCostlyError()
        }
        createCharacterToken(type, chars)
    }
}

// Splits a start tag into its attributes as the HTML tokenizer does, repeats included. `close` is the tag's `>`.
const readSourceAttributes = (html: string, tagStart: number, close: number): SourceAttribute[] => {
    const attributes: SourceAttribute[] = []
    let cursor = tagStart + 1
    while (cursor < close && !isSpace(html[cursor]) && html[cursor] !== '/') {
        cursor++
    }
    while (cursor < close) {
        if (isSpace(html[cursor]) || html[cursor] === '/') {
            cursor++
            continue
        }
        const start = cursor
        // A name may start with `=`; any later `=` starts its value.
        cursor++
        while (cursor < close && !isSpace(html[cursor]) && html[cursor] !== '/' && html[cursor] !== '=') {
            cursor++
        }
        const rawName = html.slice(start, cursor)
        let end = cursor
        while (cursor < close && isSpace(html[cursor])) {
            cursor++
        }
        const hasValue = cursor < close && html[cursor] === '='
        let quoted = false
        let valueStart = end
        if (hasValue) {
            cursor++
            while (cursor < close && isSpace(html[cursor])) {
                cursor++
            }
            const quote = html[cursor]
            quoted = cursor < close && (quote === '"' || quote === "'")
            valueStart = quoted ? cursor + 1 : cursor
            cursor = valueStart
            if (quoted) {
                // parse5 found the tag's `>` after this value, so the closing quote comes before it.
                const closingQuote = html.indexOf(quote, valueStart)
                cursor = closingQuote < 0 || closingQuote > close ? close : closingQuote + 1
            } else {
                while (cursor < close && !isSpace(html[cursor])) {
                    cursor++
                }
            }
            end = cursor
        }
        attributes.push({ rawName, hasValue, quoted, start, valueStart, end })
    }
    return attributes
}

// parse5 keeps the first attribute of each name and keys their locations by lowercased source name, so in source
// order the two lists pair up by index. Only where each one starts is taken from parse5, because a location
// ends at the name when no space follows the value.
const readAnchor = (html: string, base: number, element: Element, inComment: boolean): ScannedTag | null => {
    const location = element.sourceCodeLocation?.startTag
    if (!location) {
        return null
    }
    const start = base + location.startOffset
    const close = base + location.endOffset - 1
    if (inComment && html.slice(start, close).includes(COMMENT_OPENING)) {
        // The comment read saw the stand-in, which can also be written as itself. Inside a tag `<!--` opens no
        // comment, so the tag's own source reads it as written.
        const tag = parseFragment(html.slice(start, close + 1), PARSE_OPTIONS).childNodes.find(
            (node): node is Element => node.nodeName === 'a'
        )
        return tag ? readAnchor(html, start, tag, false) : null
    }
    const source = readSourceAttributes(html, start, close)
    const byStart = new Map(source.map((attribute) => [attribute.start, attribute]))
    const attributes: ScannedAttribute[] = []
    // Sorted, because an object lists integer-like keys such as `4` first.
    const locations = Object.entries(element.sourceCodeLocation?.attrs ?? {}).sort(
        ([, a], [, b]) => a.startOffset - b.startOffset
    )
    locations.forEach(([name, attributeLocation], index) => {
        const attribute = byStart.get(base + attributeLocation.startOffset)
        if (!attribute) {
            return
        }
        attributes.push({ ...attribute, name, value: element.attrs[index]?.value ?? '' })
    })
    const last = source[source.length - 1]
    const selfClosing = html[close - 1] === '/' && (!last || last.end < close)
    return { start, attributes, last, insertAt: selfClosing ? close - 1 : close }
}

type CommentNode = DefaultTreeAdapterMap['commentNode']

// Collects the opening `<a>` tags a browser reads, and the comments to read after them.
const scanAnchors = (
    html: string,
    root: Node,
    base: number,
    inComment: boolean,
    comments: CommentNode[],
    anchors: Map<number, ScannedTag>
): void => {
    const pending: Node[] = [root]
    while (pending.length > 0) {
        const node = pending.pop()!
        if (node.nodeName === '#comment') {
            if (!inComment) {
                comments.push(node as CommentNode)
            }
            continue
        }
        const startTag = (node as Element).sourceCodeLocation?.startTag
        // A link that a misnested end tag closes early is rebuilt as a copy with the same start tag, as often as the
        // email repeats the pattern, so each tag is read once.
        if (node.nodeName === 'a' && startTag && !anchors.has(base + startTag.startOffset)) {
            const anchor = readAnchor(html, base, node as Element, inComment)
            if (anchor) {
                anchors.set(base + startTag.startOffset, anchor)
            }
        }
        if ('childNodes' in node) {
            // A loop, not a spread: a spread passes every child as an argument, and a body can hold more than V8 takes.
            for (const child of node.childNodes) {
                pending.push(child)
            }
        }
        // An SVG or MathML element named template holds its children like any other element.
        if (node.nodeName === 'template' && 'content' in node) {
            pending.push(node.content)
        }
    }
}

type CommentMarkup = { start: number; content: string; conditional: boolean }

// Comment content is read as markup too, because Outlook renders the links inside its `<!--[if mso]>` blocks. That
// read takes a `<!--` as text, so each character is parsed at most twice however many comments a comment opens.
const commentMarkup = (html: string, comment: CommentNode): CommentMarkup | null => {
    const location = comment.sourceCodeLocation
    if (!location || !html.startsWith(COMMENT_OPENING, location.startOffset)) {
        return null
    }
    const raw = html.slice(location.startOffset, location.endOffset)
    const start = location.startOffset + COMMENT_OPENING.length
    const end = location.endOffset - (raw.endsWith('--!>') ? 4 : raw.endsWith('-->') ? 3 : 0)
    if (end <= start) {
        return null
    }
    const content = html.slice(start, end).replaceAll(COMMENT_OPENING, COMMENT_OPENING_AS_TEXT)
    return { start, content, conditional: CONDITIONAL_COMMENT.test(content) }
}

const scanComment = (
    html: string,
    comment: CommentMarkup,
    bounds: ParseBounds,
    anchors: Map<number, ScannedTag>
): void => {
    let fragment: DefaultTreeAdapterMap['documentFragment']
    try {
        let parser: Parser<DefaultTreeAdapterMap> | undefined = undefined
        parser = Parser.getFragmentParser(null, {
            ...PARSE_OPTIONS,
            treeAdapter: boundedAdapter(bounds, () => parser?.activeFormattingElements),
        })
        limitNesting(parser, bounds)
        limitFormattingListWork(parser, bounds)
        limitTokens(parser, bounds)
        parser.tokenizer.write(comment.content, true)
        fragment = parser.getFragment()
    } catch (error) {
        // No client shows a link in a plain comment, so one past the bounds is left as written rather than refusing
        // an email that renders fine. The elements it built still count, so a run of such comments cannot repeat
        // the work.
        if (error instanceof EmailHtmlTooComplexError && !comment.conditional) {
            return
        }
        throw error
    }
    scanAnchors(html, fragment, comment.start, true, [], anchors)
}

type Scan = {
    anchors: ScannedTag[]
    // The `<` of the first body end tag the tokenizer reads, or -1.
    bodyEnd: number
}

// Records the first body end tag. The tree keeps only the last one, and none that an open table makes the parser
// ignore, but the pixel has always gone before the first, where a browser still renders it. One is skipped where an
// image there would not render as one: in a template, in a select, or inside SVG or MathML, where an image closes the
// graphic. An SVG `<foreignObject>` or a MathML text element shows HTML, so an image there renders.
class BodyEndParser extends Parser<DefaultTreeAdapterMap> {
    bodyEnd = -1

    override onEndTag(token: Token.TagToken): void {
        if (this.bodyEnd < 0 && token.tagName === 'body' && token.location && this.takesImageHere()) {
            this.bodyEnd = token.location.startOffset
        }
        super.onEndTag(token)
    }

    private takesImageHere(): boolean {
        // The tokenizer tracks whether the current element is SVG or MathML that shows no HTML.
        return (
            !this.tokenizer.inForeignNode &&
            this.openElements.tmplCount === 0 &&
            !this.openElements.hasInSelectScope(spec.TAG_ID.SELECT)
        )
    }
}

const scanHtml = (html: string): Scan => {
    const bounds = parseBoundsFor(html)
    let parser: BodyEndParser | undefined = undefined
    parser = new BodyEndParser({
        ...PARSE_OPTIONS,
        treeAdapter: boundedAdapter(bounds, () => parser?.activeFormattingElements),
    })
    limitNesting(parser, bounds)
    limitFormattingListWork(parser, bounds)
    limitTokens(parser, bounds)
    parser.tokenizer.write(html, true)
    const anchors = new Map<number, ScannedTag>()
    const comments: CommentNode[] = []
    scanAnchors(html, parser.document, 0, false, comments, anchors)
    const markups = comments
        .map((comment) => commentMarkup(html, comment))
        .filter((markup): markup is CommentMarkup => markup !== null)
    // Outlook's comments are read before the plain ones, so a plain comment left unread past the budget cannot spend
    // what they need.
    for (const markup of [...markups.filter((m) => m.conditional), ...markups.filter((m) => !m.conditional)]) {
        scanComment(html, markup, bounds, anchors)
    }
    // Tree order is not source order: a link written inside a table moves before it.
    return { anchors: [...anchors.values()].sort((a, b) => a.start - b.start), bodyEnd: parser.bodyEnd }
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
// opening tag. `beforeBodyEnd` goes before the body end tag a browser reads, not a `</body>` inside an attribute, a
// comment or raw text; an email without one gets none. The rest of the email stays byte for byte as written.
export const editHrefAnchors = (
    html: string,
    edit: (anchor: HrefAnchor) => AnchorEdit | null,
    beforeBodyEnd?: string
): string => {
    const { anchors: tags, bodyEnd } = scanHtml(html)

    const pieces: string[] = []
    let copiedUpTo = 0
    // The body end tag sits outside every anchor tag, so it never splits an edit.
    let bodyEndPending = beforeBodyEnd !== undefined && bodyEnd >= 0
    const insertBodyEndMarkup = (): void => {
        pieces.push(html.slice(copiedUpTo, bodyEnd), beforeBodyEnd!)
        copiedUpTo = bodyEnd
        bodyEndPending = false
    }
    for (const tag of tags) {
        if (bodyEndPending && tag.start > bodyEnd) {
            insertBodyEndMarkup()
        }
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
        const last = tag.last
        if (last?.hasValue && !last.quoted && last.valueStart === last.end) {
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
    if (bodyEndPending) {
        insertBodyEndMarkup()
    }
    pieces.push(html.slice(copiedUpTo))
    return pieces.join('')
}

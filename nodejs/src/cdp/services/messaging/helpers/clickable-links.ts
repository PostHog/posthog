import { randomBytes } from 'node:crypto'
import { Token, Tokenizer, TokenizerMode } from 'parse5'

export const UNSUBSCRIBE_PLACEHOLDER = /\{\{\s*unsubscribe_url\s*\}\}/g

const TEXT_MODES = new Map<string, Tokenizer['state']>([
    ['title', TokenizerMode.RCDATA],
    ['textarea', TokenizerMode.RCDATA],
    ['style', TokenizerMode.RAWTEXT],
    ['xmp', TokenizerMode.RAWTEXT],
    ['iframe', TokenizerMode.RAWTEXT],
    ['noembed', TokenizerMode.RAWTEXT],
    ['noframes', TokenizerMode.RAWTEXT],
    ['noscript', TokenizerMode.RAWTEXT],
    ['script', TokenizerMode.SCRIPT_DATA],
    ['plaintext', TokenizerMode.PLAINTEXT],
])

const SVG_HTML_INTEGRATION_POINTS = new Set(['foreignobject', 'desc', 'title'])
const MATH_TEXT_INTEGRATION_POINTS = new Set(['mi', 'mo', 'mn', 'ms', 'mtext'])
const FOREIGN_BREAKOUT_TAGS = new Set([
    'b',
    'big',
    'blockquote',
    'body',
    'br',
    'center',
    'code',
    'dd',
    'div',
    'dl',
    'dt',
    'em',
    'embed',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'head',
    'hr',
    'i',
    'img',
    'li',
    'listing',
    'menu',
    'meta',
    'nobr',
    'ol',
    'p',
    'pre',
    'ruby',
    's',
    'small',
    'span',
    'strong',
    'strike',
    'sub',
    'sup',
    'table',
    'tt',
    'u',
    'ul',
    'var',
])
const SELECT_CLOSERS = new Set(['input', 'keygen', 'textarea', 'select'])
const TABLE_TAGS = new Set(['caption', 'table', 'tbody', 'tfoot', 'thead', 'tr', 'td', 'th'])
const TABLE_SECTIONS = new Set(['tbody', 'tfoot', 'thead'])
const MATH_MGLYPH_MALIGNMARK = new Set(['mglyph', 'malignmark'])
const HTML_VOID_ELEMENTS = new Set([
    'area',
    'base',
    'basefont',
    'bgsound',
    'br',
    'col',
    'embed',
    'frame',
    'hr',
    'img',
    'input',
    'keygen',
    'link',
    'meta',
    'param',
    'source',
    'track',
    'wbr',
])
const HTML_ROOT_ELEMENTS = new Set(['html', 'head', 'body'])
const HTML_IN_SCOPE_BARRIERS = new Set(['applet', 'caption', 'marquee', 'object', 'table', 'td', 'th'])
const HTML_IMPLIED_END_TAGS = new Set(['dd', 'dt', 'li', 'optgroup', 'option', 'p', 'rb', 'rp', 'rt', 'rtc'])
const HTML_P_CLOSERS = new Set([
    'address',
    'article',
    'aside',
    'blockquote',
    'center',
    'dd',
    'details',
    'dialog',
    'dir',
    'div',
    'dl',
    'dt',
    'fieldset',
    'figcaption',
    'figure',
    'footer',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'header',
    'hgroup',
    'hr',
    'li',
    'listing',
    'main',
    'menu',
    'nav',
    'ol',
    'p',
    'plaintext',
    'pre',
    'search',
    'section',
    'summary',
    'table',
    'ul',
    'xmp',
])

export const BODY_MAX_LENGTH = 1_500_000
export const UNSUBSCRIBE_TOKENS_CHECKED = 50
const TAG_MAX_ATTRIBUTES = 64
const URL_MAX_AUTHORITY_LENGTH = 255
const SENTINEL_ORIGIN = 'https://a'

const isAscii = (value: string): boolean => {
    for (let i = 0; i < value.length; i++) {
        if (value.charCodeAt(i) > 0x7f) {
            return false
        }
    }
    return true
}

type Namespace = 'svg' | 'math' | 'html'

type StackEntry = {
    tag: string
    ns: Namespace
    integration: 'none' | 'html' | 'math-text'
    inScopeBarrier: boolean
    tableTag: boolean
    inStack?: boolean
}

type TemplateFrame = {
    stack: StackEntry[]
    foreignRuns: Array<Map<string, number>>
    htmlScopes: Array<Map<string, number>>
    inSelect: boolean
    tables: Array<Set<string>>
}

const createTemplateFrame = (): TemplateFrame => ({
    stack: [],
    foreignRuns: [],
    htmlScopes: [new Map()],
    inSelect: false,
    tables: [],
})

const incCount = (counts: Map<string, number>, tag: string): void => {
    counts.set(tag, (counts.get(tag) ?? 0) + 1)
}

const decCount = (counts: Map<string, number>, tag: string): void => {
    const next = (counts.get(tag) ?? 1) - 1
    if (next <= 0) {
        counts.delete(tag)
    } else {
        counts.set(tag, next)
    }
}

class TooComplex extends Error {}

class BoundedTokenizer extends Tokenizer {
    protected override _leaveAttrName(): void {
        if ((this.currentToken as Token.TagToken).attrs.length >= TAG_MAX_ATTRIBUTES) {
            throw new TooComplex()
        }
        super._leaveAttrName()
    }
}

const ignore = (): void => {}

const isForeignBreakout = (tag: Token.TagToken): boolean =>
    FOREIGN_BREAKOUT_TAGS.has(tag.tagName) ||
    (tag.tagName === 'font' && tag.attrs.some(({ name }) => name === 'color' || name === 'face' || name === 'size'))

const isHtmlAnnotationXml = (tag: Token.TagToken): boolean => {
    const encoding = tag.attrs.find(({ name }) => name === 'encoding')
    if (!encoding || encoding.value.length > 21) {
        return false
    }
    const lower = encoding.value.toLowerCase()
    return lower === 'text/html' || lower === 'application/xhtml+xml'
}

const parsePreferencesUrl = (href: string, siteIsAscii: boolean): URL | undefined => {
    const colon = href.indexOf(':')
    if (colon === -1) {
        return undefined
    }
    let start = 0
    while (start < colon && href.charCodeAt(start) <= 0x20) {
        start += 1
    }
    let scheme = ''
    for (let i = start; i < colon; i++) {
        const ch = href.charCodeAt(i)
        if (ch === 9 || ch === 10 || ch === 13) {
            continue
        }
        if (scheme.length >= 6) {
            return undefined
        }
        scheme += String.fromCharCode(ch | 0x20)
    }
    if (scheme !== 'http' && scheme !== 'https') {
        return undefined
    }
    let pos = colon + 1
    while (pos < href.length) {
        const ch = href.charCodeAt(pos)
        if (ch === 47 || ch === 92 || ch === 9 || ch === 10 || ch === 13) {
            pos += 1
            continue
        }
        break
    }
    let authorityLength = 0
    let nonAscii = false
    while (pos < href.length) {
        const ch = href.charCodeAt(pos)
        if (ch === 47 || ch === 92 || ch === 63 || ch === 35) {
            break
        }
        if (ch !== 9 && ch !== 10 && ch !== 13) {
            authorityLength += 1
            if (authorityLength > URL_MAX_AUTHORITY_LENGTH) {
                return undefined
            }
            if (ch > 0x7f) {
                nonAscii = true
            }
        }
        pos += 1
    }
    if (authorityLength === 0 || (siteIsAscii && nonAscii)) {
        return undefined
    }
    try {
        return new URL(href)
    } catch {
        return undefined
    }
}

export const isTooLargeToCheck = ({ html, text }: { html?: string; text?: string }): boolean =>
    (html?.length ?? 0) > BODY_MAX_LENGTH || (text?.length ?? 0) > BODY_MAX_LENGTH

/**
 * Extracts clickable anchor hrefs in a single linear `parse5.Tokenizer` pass without building a DOM
 * tree, keeping worst-case work O(N) against adversarial markup. Intended as a lint against honest
 * authoring mistakes (backed by `List-Unsubscribe` headers), not full WHATWG tree construction.
 */
export const clickableHrefs = (body: string): string[] => {
    if (body.length > BODY_MAX_LENGTH) {
        return []
    }
    const hrefs = new Set<string>()
    const frames: TemplateFrame[] = [createTemplateFrame()]
    let formElement: StackEntry | null = null

    const currentFrame = (): TemplateFrame => frames[frames.length - 1]
    const topEntry = (frame: TemplateFrame): StackEntry | undefined => frame.stack[frame.stack.length - 1]

    const pushEntry = (frame: TemplateFrame, entry: StackEntry): void => {
        const prev = topEntry(frame)
        if (entry.inScopeBarrier) {
            frame.htmlScopes.push(new Map())
        }
        if (entry.ns !== 'html') {
            if (!prev || prev.ns === 'html') {
                frame.foreignRuns.push(new Map())
            }
            incCount(frame.foreignRuns[frame.foreignRuns.length - 1], entry.tag)
        } else {
            incCount(frame.htmlScopes[frame.htmlScopes.length - 1], entry.tag)
        }
        entry.inStack = true
        frame.stack.push(entry)
    }

    const popEntry = (frame: TemplateFrame): StackEntry | undefined => {
        const popped = frame.stack.pop()
        if (!popped) {
            return undefined
        }
        popped.inStack = false
        if (popped.ns !== 'html') {
            decCount(frame.foreignRuns[frame.foreignRuns.length - 1], popped.tag)
            const next = topEntry(frame)
            if (!next || next.ns === 'html') {
                frame.foreignRuns.pop()
            }
        } else {
            decCount(frame.htmlScopes[frame.htmlScopes.length - 1], popped.tag)
            if (popped.tableTag) {
                if (popped.tag === 'table') {
                    frame.tables.pop()
                } else {
                    frame.tables[frame.tables.length - 1]?.delete(popped.tag)
                }
            }
        }
        if (popped.inScopeBarrier) {
            frame.htmlScopes.pop()
        }
        return popped
    }

    const popToHtmlTag = (frame: TemplateFrame, tag: string): void => {
        while (frame.stack.length > 0) {
            const popped = popEntry(frame)
            if (popped && popped.ns === 'html' && popped.tag === tag) {
                break
            }
        }
    }

    const closeOpenP = (frame: TemplateFrame): void => {
        if ((frame.htmlScopes[frame.htmlScopes.length - 1].get('p') ?? 0) > 0) {
            popToHtmlTag(frame, 'p')
        }
    }

    const removeFormEntry = (frame: TemplateFrame, target: StackEntry): void => {
        if (!target.inStack) {
            return
        }
        for (let idx = frame.stack.length - 1; idx >= 0; idx -= 1) {
            if (frame.stack[idx] !== target) {
                continue
            }
            if (idx === frame.stack.length - 1) {
                popEntry(frame)
                return
            }
            target.inStack = false
            decCount(frame.htmlScopes[frame.htmlScopes.length - 1], 'form')
            const prev = frame.stack[idx - 1]
            const next = frame.stack[idx + 1]
            frame.stack.splice(idx, 1)
            if (prev && prev.ns !== 'html' && next && next.ns !== 'html') {
                const rightRun = frame.foreignRuns.pop()!
                const leftRun = frame.foreignRuns[frame.foreignRuns.length - 1]
                for (const [tag, count] of rightRun) {
                    leftRun.set(tag, (leftRun.get(tag) ?? 0) + count)
                }
            }
            return
        }
    }

    const popUntilTable = (frame: TemplateFrame): void => {
        while (frame.stack.length > 0) {
            const top = topEntry(frame)!
            if (top.ns === 'html' && top.tag === 'table') {
                break
            }
            popEntry(frame)
        }
    }

    const pushHtmlTableTag = (frame: TemplateFrame, tagName: string): void => {
        if (tagName === 'table') {
            const current = frame.tables[frame.tables.length - 1]
            if (current && !current.has('td') && !current.has('th') && !current.has('caption')) {
                popToHtmlTag(frame, 'table')
            }
            frame.tables.push(new Set(['table']))
            pushEntry(frame, { tag: 'table', ns: 'html', integration: 'none', inScopeBarrier: true, tableTag: true })
            return
        }
        const table = frame.tables[frame.tables.length - 1]
        if (!table) {
            return
        }
        if (tagName === 'caption') {
            popUntilTable(frame)
            table.add('caption')
            pushEntry(frame, { tag: 'caption', ns: 'html', integration: 'none', inScopeBarrier: true, tableTag: true })
        } else if (TABLE_SECTIONS.has(tagName)) {
            popUntilTable(frame)
            table.add(tagName)
            pushEntry(frame, { tag: tagName, ns: 'html', integration: 'none', inScopeBarrier: false, tableTag: true })
        } else if (tagName === 'tr') {
            if (table.has('caption')) {
                popToHtmlTag(frame, 'caption')
            }
            if (table.has('tr')) {
                popToHtmlTag(frame, 'tr')
            }
            if (!table.has('tbody') && !table.has('tfoot') && !table.has('thead')) {
                table.add('tbody')
                pushEntry(frame, {
                    tag: 'tbody',
                    ns: 'html',
                    integration: 'none',
                    inScopeBarrier: false,
                    tableTag: true,
                })
            }
            table.add('tr')
            pushEntry(frame, { tag: 'tr', ns: 'html', integration: 'none', inScopeBarrier: false, tableTag: true })
        } else if (tagName === 'td' || tagName === 'th') {
            if (table.has('caption')) {
                popToHtmlTag(frame, 'caption')
            }
            if (table.has('td')) {
                popToHtmlTag(frame, 'td')
            } else if (table.has('th')) {
                popToHtmlTag(frame, 'th')
            }
            if (!table.has('tbody') && !table.has('tfoot') && !table.has('thead')) {
                table.add('tbody')
                pushEntry(frame, {
                    tag: 'tbody',
                    ns: 'html',
                    integration: 'none',
                    inScopeBarrier: false,
                    tableTag: true,
                })
            }
            if (!table.has('tr')) {
                table.add('tr')
                pushEntry(frame, { tag: 'tr', ns: 'html', integration: 'none', inScopeBarrier: false, tableTag: true })
            }
            table.add(tagName)
            pushEntry(frame, { tag: tagName, ns: 'html', integration: 'none', inScopeBarrier: true, tableTag: true })
        }
    }

    const isHtmlStartMode = (frame: TemplateFrame, tagName: string): boolean => {
        const top = topEntry(frame)
        if (!top || top.ns === 'html' || top.integration === 'html') {
            return true
        }
        if (top.ns === 'math' && top.tag === 'annotation-xml' && tagName === 'svg') {
            return true
        }
        return top.integration === 'math-text' && !MATH_MGLYPH_MALIGNMARK.has(tagName)
    }

    const updateForeignTokenizerFlag = (): void => {
        const top = topEntry(currentFrame())
        tokenizer.inForeignNode = top !== undefined && top.ns !== 'html' && top.integration === 'none'
    }

    const tokenizer: Tokenizer = new BoundedTokenizer(
        {},
        {
            onStartTag: (tag: Token.TagToken) => {
                const frame = currentFrame()
                let inHtml = isHtmlStartMode(frame, tag.tagName)

                if (inHtml && frame.inSelect) {
                    if (SELECT_CLOSERS.has(tag.tagName)) {
                        frame.inSelect = false
                        if (tag.tagName === 'select') {
                            updateForeignTokenizerFlag()
                            return
                        }
                    } else if (frame.tables.length > 0 && TABLE_TAGS.has(tag.tagName)) {
                        frame.inSelect = false
                    } else {
                        if (tag.tagName === 'template') {
                            frames.push(createTemplateFrame())
                        } else if (tag.tagName === 'script') {
                            tokenizer.state = TokenizerMode.SCRIPT_DATA
                        }
                        updateForeignTokenizerFlag()
                        return
                    }
                }

                if (!inHtml && isForeignBreakout(tag)) {
                    while (frame.stack.length > 0) {
                        const top = topEntry(frame)!
                        if (top.ns === 'html' || top.integration !== 'none') {
                            break
                        }
                        popEntry(frame)
                    }
                    inHtml = isHtmlStartMode(frame, tag.tagName)
                }

                let anchorNs: Namespace = 'html'
                if (inHtml) {
                    if (tag.tagName === 'form') {
                        const inTemplate = frames.length > 1
                        const top = topEntry(frame)
                        const inTableContext =
                            top !== undefined &&
                            top.ns === 'html' &&
                            (top.tag === 'table' || TABLE_SECTIONS.has(top.tag) || top.tag === 'tr')
                        if (inTableContext) {
                            if (!formElement && !inTemplate) {
                                formElement = {
                                    tag: 'form',
                                    ns: 'html',
                                    integration: 'none',
                                    inScopeBarrier: false,
                                    tableTag: false,
                                    inStack: false,
                                }
                            }
                        } else if (!formElement || inTemplate) {
                            closeOpenP(frame)
                            const entry: StackEntry = {
                                tag: 'form',
                                ns: 'html',
                                integration: 'none',
                                inScopeBarrier: false,
                                tableTag: false,
                            }
                            pushEntry(frame, entry)
                            if (!inTemplate) {
                                formElement = entry
                            }
                        }
                    } else {
                        if (HTML_P_CLOSERS.has(tag.tagName)) {
                            closeOpenP(frame)
                        }
                        if (tag.tagName === 'svg') {
                            if (!tag.selfClosing) {
                                pushEntry(frame, {
                                    tag: 'svg',
                                    ns: 'svg',
                                    integration: 'none',
                                    inScopeBarrier: false,
                                    tableTag: false,
                                })
                            }
                        } else if (tag.tagName === 'math') {
                            if (!tag.selfClosing) {
                                pushEntry(frame, {
                                    tag: 'math',
                                    ns: 'math',
                                    integration: 'none',
                                    inScopeBarrier: false,
                                    tableTag: false,
                                })
                            }
                        } else if (tag.tagName === 'template') {
                            frames.push(createTemplateFrame())
                        } else if (tag.tagName === 'select') {
                            frame.inSelect = true
                        } else if (TABLE_TAGS.has(tag.tagName)) {
                            pushHtmlTableTag(frame, tag.tagName)
                        } else if (TEXT_MODES.has(tag.tagName)) {
                            tokenizer.state = TEXT_MODES.get(tag.tagName)!
                        } else if (!HTML_VOID_ELEMENTS.has(tag.tagName) && !HTML_ROOT_ELEMENTS.has(tag.tagName)) {
                            pushEntry(frame, {
                                tag: tag.tagName,
                                ns: 'html',
                                integration: 'none',
                                inScopeBarrier: HTML_IN_SCOPE_BARRIERS.has(tag.tagName),
                                tableTag: false,
                            })
                        }
                    }
                } else {
                    const parentNs = topEntry(frame)!.ns
                    const elementNs: Namespace = parentNs
                    anchorNs = elementNs
                    if (!tag.selfClosing) {
                        const integration: StackEntry['integration'] =
                            parentNs === 'svg' && SVG_HTML_INTEGRATION_POINTS.has(tag.tagName)
                                ? 'html'
                                : parentNs === 'math' && MATH_TEXT_INTEGRATION_POINTS.has(tag.tagName)
                                  ? 'math-text'
                                  : parentNs === 'math' && tag.tagName === 'annotation-xml' && isHtmlAnnotationXml(tag)
                                    ? 'html'
                                    : 'none'
                        const inScopeBarrier =
                            integration !== 'none' || (parentNs === 'math' && tag.tagName === 'annotation-xml')
                        pushEntry(frame, {
                            tag: tag.tagName,
                            ns: elementNs,
                            integration,
                            inScopeBarrier,
                            tableTag: false,
                        })
                    }
                }

                updateForeignTokenizerFlag()

                if (tag.tagName === 'a' && frames.length === 1 && !frame.inSelect) {
                    const href =
                        tag.attrs.find(({ name }) => name === 'href') ??
                        (anchorNs === 'svg' ? tag.attrs.find(({ name }) => name === 'xlink:href') : undefined)
                    if (href) {
                        hrefs.add(href.value)
                    }
                }
            },
            onEndTag: (tag: Token.TagToken) => {
                const frame = currentFrame()
                if (tag.tagName === 'template' && frames.length > 1) {
                    frames.pop()
                    updateForeignTokenizerFlag()
                    return
                }

                const top = topEntry(frame)
                if (!frame.inSelect && top && top.ns !== 'html') {
                    if (tag.tagName === 'p' || tag.tagName === 'br') {
                        while (frame.stack.length > 0) {
                            const cur = topEntry(frame)!
                            if (cur.ns === 'html' || cur.integration !== 'none') {
                                break
                            }
                            popEntry(frame)
                        }
                        if (tag.tagName === 'br') {
                            updateForeignTokenizerFlag()
                            return
                        }
                    } else {
                        const foreignRun = frame.foreignRuns[frame.foreignRuns.length - 1]
                        if ((foreignRun?.get(tag.tagName) ?? 0) > 0) {
                            while (frame.stack.length > 0) {
                                const popped = popEntry(frame)
                                if (popped && popped.tag === tag.tagName) {
                                    break
                                }
                            }
                            updateForeignTokenizerFlag()
                            return
                        }
                    }
                }

                if (frame.inSelect) {
                    if (tag.tagName === 'select') {
                        frame.inSelect = false
                    } else if (TABLE_TAGS.has(tag.tagName) && frame.tables[frame.tables.length - 1]?.has(tag.tagName)) {
                        frame.inSelect = false
                        popToHtmlTag(frame, tag.tagName)
                    }
                } else if (TABLE_TAGS.has(tag.tagName)) {
                    if (frame.tables[frame.tables.length - 1]?.has(tag.tagName)) {
                        popToHtmlTag(frame, tag.tagName)
                    }
                } else if (tag.tagName === 'form') {
                    const inTemplate = frames.length > 1
                    const activeForm = formElement
                    if (!inTemplate) {
                        formElement = null
                    }
                    if (
                        (activeForm !== null || inTemplate) &&
                        (frame.htmlScopes[frame.htmlScopes.length - 1].get('form') ?? 0) > 0
                    ) {
                        while (frame.stack.length > 0) {
                            const cur = topEntry(frame)!
                            if (cur.ns !== 'html' || !HTML_IMPLIED_END_TAGS.has(cur.tag)) {
                                break
                            }
                            popEntry(frame)
                        }
                        if (inTemplate) {
                            popToHtmlTag(frame, 'form')
                        } else if (activeForm) {
                            removeFormEntry(frame, activeForm)
                        }
                    }
                } else if ((frame.htmlScopes[frame.htmlScopes.length - 1].get(tag.tagName) ?? 0) > 0) {
                    popToHtmlTag(frame, tag.tagName)
                }

                updateForeignTokenizerFlag()
            },
            onComment: ignore,
            onDoctype: ignore,
            onEof: ignore,
            onCharacter: ignore,
            onNullCharacter: ignore,
            onWhitespaceCharacter: ignore,
        }
    )
    try {
        tokenizer.write(body, true)
    } catch (error) {
        if (error instanceof TooComplex) {
            return []
        }
        throw error
    }
    return [...hrefs]
}

export const filledUnsubscribeLength = (body: string | undefined, url: string | undefined): number => {
    if (!body || !url) {
        return body?.length ?? 0
    }
    let length = body.length
    for (const placeholder of body.matchAll(UNSUBSCRIBE_PLACEHOLDER)) {
        length += url.length - placeholder[0].length
    }
    return length
}

export const replaceUnsubscribePlaceholder = (body: string, url: string): string =>
    body.replace(UNSUBSCRIBE_PLACEHOLDER, () => url)

const unusedSentinelUrl = (source: string): { origin: string; pathname: string; url: string } => {
    for (let attempt = 0; attempt < 4; attempt += 1) {
        const token = randomBytes(6).toString('base64url')
        if (!source.includes(token)) {
            const pathname = `/${token}/`
            return { origin: SENTINEL_ORIGIN, pathname, url: `${SENTINEL_ORIGIN}${pathname}` }
        }
    }
    const used = new Set<string>()
    for (const match of source.matchAll(/_[0-9a-z]{5}/g)) {
        used.add(match[0])
    }
    for (let n = 0; ; n += 1) {
        const token = `_${n.toString(36).padStart(5, '0')}`
        if (!used.has(token)) {
            const pathname = `/${token}/`
            return { origin: SENTINEL_ORIGIN, pathname, url: `${SENTINEL_ORIGIN}${pathname}` }
        }
    }
}

/**
 * Checks whether replacing raw `{{ unsubscribe_url }}` placeholders produces a clickable preferences
 * link in `html` (or a placeholder in plain `text` when `html` is empty), matching the delivery-time
 * substitution so entity-encoded placeholders and foreign-host wrapper URLs are rejected upfront.
 */
export const hasReplaceableUnsubscribeLink = ({ html, text }: { html?: string; text?: string }): boolean => {
    if (html) {
        if (html.length > BODY_MAX_LENGTH || html.search(UNSUBSCRIBE_PLACEHOLDER) === -1) {
            return false
        }
        const sentinel = unusedSentinelUrl(html)
        const filled = replaceUnsubscribePlaceholder(html, sentinel.url)
        return clickableHrefs(filled).some((href) => {
            const page = parsePreferencesUrl(href, true)
            return page !== undefined && page.origin === sentinel.origin && page.pathname === sentinel.pathname
        })
    }
    return (text ?? '').search(UNSUBSCRIBE_PLACEHOLDER) !== -1
}

export const preferencesTokensInBody = (body: { html?: string; text?: string }, siteUrl: string): string[] => {
    const preferencesPage = `${siteUrl}/messaging-preferences/`
    const tokens = new Set<string>()
    const addPath = (path: string): void => {
        const page = path.split(/[?#]/)[0]
        if (/^[^/]+\/$/.test(page)) {
            tokens.add(page.slice(0, -1))
        }
    }
    if (body.html) {
        const siteIsAscii = isAscii(siteUrl)
        for (const href of clickableHrefs(body.html)) {
            const page = parsePreferencesUrl(href, siteIsAscii)
            const path = page ? `${page.origin}${page.pathname}` : ''
            if (path.startsWith(preferencesPage)) {
                addPath(path.slice(preferencesPage.length))
                if (tokens.size >= UNSUBSCRIBE_TOKENS_CHECKED) {
                    break
                }
            }
        }
    } else {
        for (const rest of (body.text ?? '').split(preferencesPage).slice(1)) {
            const match = rest.match(/^[^\s/?#]+\//)
            if (match) {
                addPath(match[0])
                if (tokens.size >= UNSUBSCRIBE_TOKENS_CHECKED) {
                    break
                }
            }
        }
    }
    return [...tokens]
}

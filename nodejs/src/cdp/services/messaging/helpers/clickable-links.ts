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
const SELECT_IN_TABLE_CLOSERS = new Set(['caption', 'table', 'tbody', 'tfoot', 'thead', 'tr', 'td', 'th'])
const TABLE_SECTIONS = new Set(['tbody', 'tfoot', 'thead'])

export const BODY_MAX_LENGTH = 1_500_000
export const UNSUBSCRIBE_TOKENS_CHECKED = 50
const TAG_MAX_ATTRIBUTES = 64
const URL_MAX_AUTHORITY_LENGTH = 255
const SENTINEL_ORIGIN = 'https://a'

export type ClickableHrefsStats = {
    tokens: number
    contextOps: number
}

export type HasReplaceableStats = ClickableHrefsStats & {
    sentinelScans: number
}

export type PreferencesTokensStats = {
    urlParses: number
}

const isAscii = (value: string): boolean => {
    for (let i = 0; i < value.length; i++) {
        if (value.charCodeAt(i) > 0x7f) {
            return false
        }
    }
    return true
}

type Namespace = 'svg' | 'math' | 'html'

type TemplateFrame = {
    contexts: Array<{ tag: string; ns: Namespace }>
    openCounts: Map<string, number>
    inSelect: boolean
    tables: Array<Set<string>>
}

const createTemplateFrame = (): TemplateFrame => ({
    contexts: [],
    openCounts: new Map(),
    inSelect: false,
    tables: [],
})

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

const parsePreferencesUrl = (href: string, siteIsAscii: boolean, stats?: PreferencesTokensStats): URL | undefined => {
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
    if (stats) {
        stats.urlParses += 1
    }
    try {
        return new URL(href)
    } catch {
        return undefined
    }
}

export const isTooLargeToCheck = ({ html, text }: { html?: string; text?: string }): boolean =>
    (html?.length ?? 0) > BODY_MAX_LENGTH || (text?.length ?? 0) > BODY_MAX_LENGTH

const trackTableStart = (tables: Array<Set<string>>, tagName: string): void => {
    if (tagName === 'table') {
        const current = tables[tables.length - 1]
        if (!current || current.has('td') || current.has('th') || current.has('caption')) {
            tables.push(new Set(['table']))
        } else {
            tables[tables.length - 1] = new Set(['table'])
        }
        return
    }
    const table = tables[tables.length - 1]
    if (!table) {
        return
    }
    if (tagName === 'caption') {
        table.delete('tbody')
        table.delete('tfoot')
        table.delete('thead')
        table.delete('tr')
        table.delete('td')
        table.delete('th')
        table.add('caption')
    } else if (TABLE_SECTIONS.has(tagName)) {
        table.delete('caption')
        table.delete('tbody')
        table.delete('tfoot')
        table.delete('thead')
        table.delete('tr')
        table.delete('td')
        table.delete('th')
        table.add(tagName)
    } else if (tagName === 'tr') {
        table.delete('caption')
        table.delete('tr')
        table.delete('td')
        table.delete('th')
        if (!table.has('tbody') && !table.has('tfoot') && !table.has('thead')) {
            table.add('tbody')
        }
        table.add('tr')
    } else if (tagName === 'td' || tagName === 'th') {
        table.delete('caption')
        table.delete('td')
        table.delete('th')
        if (!table.has('tbody') && !table.has('tfoot') && !table.has('thead')) {
            table.add('tbody')
        }
        table.add('tr')
        table.add(tagName)
    }
}

const trackTableEnd = (tables: Array<Set<string>>, tagName: string): void => {
    const table = tables[tables.length - 1]
    if (!table || !table.has(tagName)) {
        return
    }
    if (tagName === 'table') {
        tables.pop()
    } else if (tagName === 'caption') {
        table.delete('caption')
    } else if (TABLE_SECTIONS.has(tagName)) {
        table.delete(tagName)
        table.delete('tr')
        table.delete('td')
        table.delete('th')
    } else if (tagName === 'tr') {
        table.delete('tr')
        table.delete('td')
        table.delete('th')
    } else if (tagName === 'td' || tagName === 'th') {
        table.delete(tagName)
    }
}

/**
 * Extracts clickable anchor hrefs in a single linear `parse5.Tokenizer` pass without building a DOM
 * tree, keeping worst-case work O(N) against adversarial markup. Intended as a lint against honest
 * authoring mistakes (backed by `List-Unsubscribe` headers), not full WHATWG tree construction.
 */
export const clickableHrefs = (body: string, stats?: ClickableHrefsStats): string[] => {
    if (body.length > BODY_MAX_LENGTH) {
        return []
    }
    const hrefs = new Set<string>()
    const frames: TemplateFrame[] = [createTemplateFrame()]

    const currentFrame = (): TemplateFrame => frames[frames.length - 1]
    const currentNs = (): Namespace => {
        const { contexts } = currentFrame()
        return contexts.length > 0 ? contexts[contexts.length - 1].ns : 'html'
    }
    const pushContext = (tag: string, ns: Namespace): void => {
        const frame = currentFrame()
        frame.contexts.push({ tag, ns })
        frame.openCounts.set(tag, (frame.openCounts.get(tag) ?? 0) + 1)
        if (stats) {
            stats.contextOps += 1
        }
    }
    const popContext = (): void => {
        const frame = currentFrame()
        const popped = frame.contexts.pop()
        if (popped) {
            frame.openCounts.set(popped.tag, (frame.openCounts.get(popped.tag) ?? 1) - 1)
            if (stats) {
                stats.contextOps += 1
            }
        }
    }
    const popToTag = (tag: string): void => {
        const frame = currentFrame()
        if ((frame.openCounts.get(tag) ?? 0) === 0) {
            return
        }
        while (frame.contexts.length > 0) {
            const top = frame.contexts[frame.contexts.length - 1]
            popContext()
            if (top.tag === tag) {
                break
            }
        }
    }
    const pushTemplateFrame = (): void => {
        frames.push(createTemplateFrame())
        if (stats) {
            stats.contextOps += 1
        }
    }
    const popTemplateFrame = (): void => {
        if (frames.length > 1) {
            frames.pop()
            if (stats) {
                stats.contextOps += 1
            }
        }
    }

    const tokenizer: Tokenizer = new BoundedTokenizer(
        {},
        {
            onStartTag: (tag: Token.TagToken) => {
                if (stats) {
                    stats.tokens += 1
                }
                const frame = currentFrame()
                let ns = currentNs()

                if (ns === 'html' && frame.inSelect) {
                    if (SELECT_CLOSERS.has(tag.tagName)) {
                        frame.inSelect = false
                        if (tag.tagName === 'select') {
                            return
                        }
                    } else if (frame.tables.length > 0 && SELECT_IN_TABLE_CLOSERS.has(tag.tagName)) {
                        frame.inSelect = false
                    } else {
                        if (tag.tagName === 'template') {
                            pushTemplateFrame()
                        } else if (tag.tagName === 'script') {
                            tokenizer.state = TokenizerMode.SCRIPT_DATA
                        }
                        return
                    }
                }

                if (ns !== 'html' && isForeignBreakout(tag)) {
                    while (frame.contexts.length > 0 && frame.contexts[frame.contexts.length - 1].ns !== 'html') {
                        popContext()
                    }
                    ns = currentNs()
                }

                if (ns === 'html') {
                    if (tag.tagName === 'svg' && !tag.selfClosing) {
                        pushContext('svg', 'svg')
                    } else if (tag.tagName === 'math' && !tag.selfClosing) {
                        pushContext('math', 'math')
                    } else if (tag.tagName === 'template') {
                        pushTemplateFrame()
                    } else if (tag.tagName === 'select') {
                        frame.inSelect = true
                    } else {
                        if (SELECT_IN_TABLE_CLOSERS.has(tag.tagName)) {
                            trackTableStart(frame.tables, tag.tagName)
                        }
                        tokenizer.state = TEXT_MODES.get(tag.tagName) ?? tokenizer.state
                    }
                } else if (ns === 'svg' && SVG_HTML_INTEGRATION_POINTS.has(tag.tagName) && !tag.selfClosing) {
                    pushContext(tag.tagName, 'html')
                } else if (
                    ns === 'math' &&
                    (MATH_TEXT_INTEGRATION_POINTS.has(tag.tagName) ||
                        (tag.tagName === 'annotation-xml' && isHtmlAnnotationXml(tag))) &&
                    !tag.selfClosing
                ) {
                    pushContext(tag.tagName, 'html')
                } else if (tag.tagName === 'svg' && !tag.selfClosing) {
                    pushContext('svg', 'svg')
                } else if (tag.tagName === 'math' && !tag.selfClosing) {
                    pushContext('math', 'math')
                }

                tokenizer.inForeignNode = currentNs() !== 'html'

                if (tag.tagName === 'a' && frames.length === 1 && !frame.inSelect) {
                    const href =
                        tag.attrs.find(({ name }) => name === 'href') ??
                        (ns === 'svg' ? tag.attrs.find(({ name }) => name === 'xlink:href') : undefined)
                    if (href) {
                        hrefs.add(href.value)
                    }
                }
            },
            onEndTag: (tag: Token.TagToken) => {
                if (stats) {
                    stats.tokens += 1
                }
                const frame = currentFrame()
                const ns = currentNs()
                if (tag.tagName === 'template' && frames.length > 1) {
                    popTemplateFrame()
                } else if (ns !== 'html' && (tag.tagName === 'p' || tag.tagName === 'br')) {
                    while (frame.contexts.length > 0 && frame.contexts[frame.contexts.length - 1].ns !== 'html') {
                        popContext()
                    }
                } else if (ns === 'html' && frame.inSelect) {
                    if (tag.tagName === 'select') {
                        frame.inSelect = false
                    } else if (
                        SELECT_IN_TABLE_CLOSERS.has(tag.tagName) &&
                        frame.tables[frame.tables.length - 1]?.has(tag.tagName)
                    ) {
                        frame.inSelect = false
                        trackTableEnd(frame.tables, tag.tagName)
                    }
                } else if (ns === 'html' && SELECT_IN_TABLE_CLOSERS.has(tag.tagName)) {
                    trackTableEnd(frame.tables, tag.tagName)
                } else if (
                    tag.tagName === 'svg' ||
                    tag.tagName === 'math' ||
                    SVG_HTML_INTEGRATION_POINTS.has(tag.tagName) ||
                    MATH_TEXT_INTEGRATION_POINTS.has(tag.tagName) ||
                    tag.tagName === 'annotation-xml'
                ) {
                    popToTag(tag.tagName)
                }
                tokenizer.inForeignNode = currentNs() !== 'html'
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

const unusedSentinelUrl = (
    source: string,
    stats?: HasReplaceableStats
): { origin: string; pathname: string; url: string } => {
    for (let attempt = 0; attempt < 4; attempt += 1) {
        const token = randomBytes(6).toString('base64url')
        if (stats) {
            stats.sentinelScans += 1
        }
        if (!source.includes(token)) {
            const pathname = `/${token}/`
            return { origin: SENTINEL_ORIGIN, pathname, url: `${SENTINEL_ORIGIN}${pathname}` }
        }
    }
    const used = new Set<string>()
    if (stats) {
        stats.sentinelScans += 1
    }
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
export const hasReplaceableUnsubscribeLink = (
    { html, text }: { html?: string; text?: string },
    stats?: HasReplaceableStats
): boolean => {
    if (html) {
        if (html.length > BODY_MAX_LENGTH || html.search(UNSUBSCRIBE_PLACEHOLDER) === -1) {
            return false
        }
        const sentinel = unusedSentinelUrl(html, stats)
        const filled = replaceUnsubscribePlaceholder(html, sentinel.url)
        return clickableHrefs(filled, stats).some((href) => {
            const page = parsePreferencesUrl(href, true)
            return page !== undefined && page.origin === sentinel.origin && page.pathname === sentinel.pathname
        })
    }
    return (text ?? '').search(UNSUBSCRIBE_PLACEHOLDER) !== -1
}

export const preferencesTokensInBody = (
    body: { html?: string; text?: string },
    siteUrl: string,
    stats?: PreferencesTokensStats
): string[] => {
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
            const page = parsePreferencesUrl(href, siteIsAscii, stats)
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

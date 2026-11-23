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

export const BODY_MAX_LENGTH = 1_500_000
export const UNSUBSCRIBE_TOKENS_CHECKED = 50
const TAG_MAX_ATTRIBUTES = 64
const URL_MAX_AUTHORITY_LENGTH = 255

const isAscii = (value: string): boolean => {
    for (let i = 0; i < value.length; i++) {
        if (value.charCodeAt(i) > 0x7f) {
            return false
        }
    }
    return true
}

type Namespace = 'svg' | 'math' | 'html'

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

export const clickableHrefs = (body: string): string[] => {
    if (body.length > BODY_MAX_LENGTH) {
        return []
    }
    const hrefs = new Set<string>()
    let templateDepth = 0
    let inSelect = false
    const contexts: Array<{ tag: string; ns: Namespace }> = []
    const openCounts = new Map<string, number>()

    const currentNs = (): Namespace => (contexts.length > 0 ? contexts[contexts.length - 1].ns : 'html')
    const pushContext = (tag: string, ns: Namespace): void => {
        contexts.push({ tag, ns })
        openCounts.set(tag, (openCounts.get(tag) ?? 0) + 1)
    }
    const popContext = (): void => {
        const popped = contexts.pop()
        if (popped) {
            openCounts.set(popped.tag, (openCounts.get(popped.tag) ?? 1) - 1)
        }
    }
    const popToTag = (tag: string): void => {
        if ((openCounts.get(tag) ?? 0) === 0) {
            return
        }
        while (contexts.length > 0) {
            const top = contexts[contexts.length - 1]
            popContext()
            if (top.tag === tag) {
                break
            }
        }
    }

    const tokenizer: Tokenizer = new BoundedTokenizer(
        {},
        {
            onStartTag: (tag: Token.TagToken) => {
                let ns = currentNs()

                if (ns === 'html' && inSelect && templateDepth === 0) {
                    if (SELECT_CLOSERS.has(tag.tagName)) {
                        inSelect = false
                        if (tag.tagName === 'select') {
                            return
                        }
                    } else {
                        if (tag.tagName === 'template') {
                            templateDepth += 1
                        } else if (tag.tagName === 'script') {
                            tokenizer.state = TokenizerMode.SCRIPT_DATA
                        }
                        return
                    }
                }

                if (ns !== 'html' && isForeignBreakout(tag)) {
                    while (contexts.length > 0 && contexts[contexts.length - 1].ns !== 'html') {
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
                        templateDepth += 1
                    } else if (templateDepth === 0 && tag.tagName === 'select') {
                        inSelect = true
                    } else {
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

                if (tag.tagName === 'a' && templateDepth === 0 && !inSelect) {
                    const href =
                        tag.attrs.find(({ name }) => name === 'href') ??
                        (ns === 'svg' ? tag.attrs.find(({ name }) => name === 'xlink:href') : undefined)
                    if (href) {
                        hrefs.add(href.value)
                    }
                }
            },
            onEndTag: (tag: Token.TagToken) => {
                if (tag.tagName === 'template' && templateDepth > 0) {
                    templateDepth -= 1
                } else if (tag.tagName === 'select' && templateDepth === 0 && inSelect) {
                    inSelect = false
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

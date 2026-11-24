import { randomBytes } from 'node:crypto'
import { Token, Tokenizer, TokenizerMode } from 'parse5'

export const UNSUBSCRIBE_PLACEHOLDER = /\{\{\s*unsubscribe_url\s*\}\}/g

export const UNSUPPORTED_MARKETING_HTML_TAGS: ReadonlySet<string> = new Set([
    'frameset',
    'template',
    'select',
    'svg',
    'math',
    'noscript',
])

export const UNSUBSCRIBE_LINK_REQUIRED_MESSAGE =
    "A marketing email needs a clickable unsubscribe link in a plain <a href> in the body. Bodies with frameset, template, select, svg, math, or noscript tags aren't accepted for marketing sends."

const TEXT_MODES = new Map<string, Tokenizer['state']>([
    ['title', TokenizerMode.RCDATA],
    ['textarea', TokenizerMode.RCDATA],
    ['style', TokenizerMode.RAWTEXT],
    ['xmp', TokenizerMode.RAWTEXT],
    ['iframe', TokenizerMode.RAWTEXT],
    ['noembed', TokenizerMode.RAWTEXT],
    ['noframes', TokenizerMode.RAWTEXT],
    ['script', TokenizerMode.SCRIPT_DATA],
    ['plaintext', TokenizerMode.PLAINTEXT],
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

class TooComplex extends Error {}
class UnsupportedMarkup extends Error {}

class BoundedTokenizer extends Tokenizer {
    protected override _leaveAttrName(): void {
        if ((this.currentToken as Token.TagToken).attrs.length >= TAG_MAX_ATTRIBUTES) {
            throw new TooComplex()
        }
        super._leaveAttrName()
    }
}

const ignore = (): void => {}

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
 * Extracts plain HTML `<a href>` values outside raw-text elements and comments in one linear
 * `parse5.Tokenizer` pass. Fails closed if any of `UNSUPPORTED_MARKETING_HTML_TAGS` appears
 * anywhere outside raw-text elements and comments.
 */
export const clickableHrefs = (body: string): string[] => {
    if (body.length > BODY_MAX_LENGTH) {
        return []
    }
    const hrefs = new Set<string>()

    const tokenizer: Tokenizer = new BoundedTokenizer(
        {},
        {
            onStartTag: (tag: Token.TagToken) => {
                if (UNSUPPORTED_MARKETING_HTML_TAGS.has(tag.tagName)) {
                    throw new UnsupportedMarkup()
                }
                const textMode = TEXT_MODES.get(tag.tagName)
                if (textMode !== undefined) {
                    tokenizer.state = textMode
                    return
                }
                if (tag.tagName === 'a') {
                    const href = tag.attrs.find(({ name }) => name === 'href')
                    if (href) {
                        hrefs.add(href.value)
                    }
                }
            },
            onEndTag: (tag: Token.TagToken) => {
                if (UNSUPPORTED_MARKETING_HTML_TAGS.has(tag.tagName)) {
                    throw new UnsupportedMarkup()
                }
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
        if (error instanceof UnsupportedMarkup || error instanceof TooComplex) {
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

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

export const BODY_MAX_LENGTH = 1_500_000
export const UNSUBSCRIBE_TOKENS_CHECKED = 50
const TAG_MAX_ATTRIBUTES = 64

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

export const isTooLargeToCheck = ({ html, text }: { html?: string; text?: string }): boolean =>
    (html?.length ?? 0) > BODY_MAX_LENGTH || (text?.length ?? 0) > BODY_MAX_LENGTH

export const clickableHrefs = (body: string): string[] => {
    if (body.length > BODY_MAX_LENGTH) {
        return []
    }
    const hrefs = new Set<string>()
    let templateDepth = 0
    let inSelect = false
    let svgDepth = 0
    let mathDepth = 0
    let foreignObjectDepth = 0

    const inForeign = (): boolean => (svgDepth > 0 || mathDepth > 0) && foreignObjectDepth === 0

    const tokenizer: Tokenizer = new BoundedTokenizer(
        {},
        {
            onStartTag: (tag: Token.TagToken) => {
                const foreign = inForeign()
                const inRawSelect = inSelect && templateDepth === 0
                if (!inRawSelect && tag.tagName === 'svg' && !tag.selfClosing) {
                    svgDepth += 1
                } else if (!inRawSelect && tag.tagName === 'math' && !tag.selfClosing) {
                    mathDepth += 1
                } else if (tag.tagName === 'foreignobject' && svgDepth > 0 && !tag.selfClosing) {
                    foreignObjectDepth += 1
                } else if (!foreign && tag.tagName === 'template') {
                    templateDepth += 1
                } else if (!foreign && templateDepth === 0 && tag.tagName === 'select') {
                    inSelect = true
                }

                const nowForeign = inForeign()
                tokenizer.inForeignNode = nowForeign

                if (!nowForeign) {
                    if (inSelect && templateDepth === 0) {
                        if (tag.tagName === 'script') {
                            tokenizer.state = TokenizerMode.SCRIPT_DATA
                        }
                    } else {
                        tokenizer.state = TEXT_MODES.get(tag.tagName) ?? tokenizer.state
                    }
                } else if (tag.tagName === 'style' && !tag.selfClosing) {
                    tokenizer.state = TokenizerMode.RAWTEXT
                }

                if (tag.tagName === 'a' && templateDepth === 0 && !inSelect) {
                    const href =
                        tag.attrs.find(({ name }) => name === 'href') ??
                        (svgDepth > 0 && foreignObjectDepth === 0
                            ? tag.attrs.find(({ name }) => name === 'xlink:href')
                            : undefined)
                    if (href) {
                        hrefs.add(href.value)
                    }
                }
            },
            onEndTag: (tag: Token.TagToken) => {
                if (tag.tagName === 'foreignobject' && foreignObjectDepth > 0) {
                    foreignObjectDepth -= 1
                } else if (tag.tagName === 'svg' && svgDepth > 0) {
                    svgDepth -= 1
                    if (svgDepth === 0) {
                        foreignObjectDepth = 0
                    }
                } else if (tag.tagName === 'math' && mathDepth > 0) {
                    mathDepth -= 1
                } else if (tag.tagName === 'template' && templateDepth > 0) {
                    templateDepth -= 1
                } else if (tag.tagName === 'select' && templateDepth === 0) {
                    inSelect = false
                }
                tokenizer.inForeignNode = inForeign()
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
    const paths = body.html
        ? clickableHrefs(body.html).flatMap((href) => {
              const page = URL.canParse(href) ? new URL(href) : undefined
              const path = page ? `${page.origin}${page.pathname}` : ''
              return path.startsWith(preferencesPage) ? [path.slice(preferencesPage.length)] : []
          })
        : (body.text ?? '')
              .split(preferencesPage)
              .slice(1)
              .flatMap((rest) => rest.match(/^[^\s/?#]+\//) ?? [])
    return [
        ...new Set(
            paths.flatMap((path) => {
                const page = path.split(/[?#]/)[0]
                return /^[^/]+\/$/.test(page) ? [page.slice(0, -1)] : []
            })
        ),
    ].slice(0, UNSUBSCRIBE_TOKENS_CHECKED)
}

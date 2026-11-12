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

const FOREIGN_ROOTS = new Set(['svg', 'math'])

const HTML_INTEGRATION_POINTS = new Set(['foreignobject', 'desc', 'title', 'mi', 'mo', 'mn', 'ms', 'mtext'])

type Boundary = { tagName: string; foreign: boolean }

const ignore = (): void => {}

export const clickableHrefs = (body: string): string[] => {
    const hrefs: string[] = []
    const boundaries: Boundary[] = []
    let templateDepth = 0
    const inForeign = (): boolean => boundaries[boundaries.length - 1]?.foreign ?? false
    const tokenizer: Tokenizer = new Tokenizer(
        {},
        {
            onStartTag: (tag: Token.TagToken) => {
                const foreign = inForeign()
                if (!foreign) {
                    tokenizer.state = TEXT_MODES.get(tag.tagName) ?? tokenizer.state
                }
                const switchesNamespace = foreign
                    ? HTML_INTEGRATION_POINTS.has(tag.tagName)
                    : FOREIGN_ROOTS.has(tag.tagName)
                if (!tag.selfClosing && switchesNamespace) {
                    boundaries.push({ tagName: tag.tagName, foreign: !foreign })
                } else if (!tag.selfClosing && !foreign && tag.tagName === 'template') {
                    boundaries.push({ tagName: tag.tagName, foreign })
                    templateDepth += 1
                }
                tokenizer.inForeignNode = inForeign()
                const href = tag.tagName === 'a' ? tag.attrs.find(({ name }) => name === 'href') : undefined
                if (href && templateDepth === 0) {
                    hrefs.push(href.value)
                }
            },
            onEndTag: (tag: Token.TagToken) => {
                if (boundaries[boundaries.length - 1]?.tagName === tag.tagName) {
                    templateDepth -= boundaries.pop()?.tagName === 'template' ? 1 : 0
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
    tokenizer.write(body, true)
    return hrefs
}

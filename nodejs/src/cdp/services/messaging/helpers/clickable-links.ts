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

const UNFOLLOWED_CONTENT = new Set(['svg', 'math', 'select', 'template'])

const FRAMESET = /<frameset/i

const ignore = (): void => {}

export const clickableHrefs = (body: string): string[] => {
    if (FRAMESET.test(body)) {
        return []
    }
    const hrefs: string[] = []
    const tokenizer: Tokenizer = new Tokenizer(
        {},
        {
            onStartTag: (tag: Token.TagToken) => {
                if (UNFOLLOWED_CONTENT.has(tag.tagName)) {
                    tokenizer.pause()
                    return
                }
                tokenizer.state = TEXT_MODES.get(tag.tagName) ?? tokenizer.state
                const href = tag.tagName === 'a' ? tag.attrs.find(({ name }) => name === 'href') : undefined
                if (href) {
                    hrefs.push(href.value)
                }
            },
            onEndTag: ignore,
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

import { Token, Tokenizer, TokenizerMode } from 'parse5'

export const UNSUBSCRIBE_PLACEHOLDER = /\{\{\s*unsubscribe_url\s*\}\}/g

const TEXT_MODES: Record<string, Tokenizer['state']> = {
    title: TokenizerMode.RCDATA,
    textarea: TokenizerMode.RCDATA,
    style: TokenizerMode.RAWTEXT,
    xmp: TokenizerMode.RAWTEXT,
    iframe: TokenizerMode.RAWTEXT,
    noembed: TokenizerMode.RAWTEXT,
    noframes: TokenizerMode.RAWTEXT,
    noscript: TokenizerMode.RAWTEXT,
    script: TokenizerMode.SCRIPT_DATA,
    plaintext: TokenizerMode.PLAINTEXT,
}

const FOREIGN_ROOTS = new Set(['svg', 'math'])

const ignore = (): void => {}

export const clickableHrefs = (body: string): string[] => {
    const hrefs: string[] = []
    let foreignDepth = 0
    let templateDepth = 0
    const tokenizer: Tokenizer = new Tokenizer(
        {},
        {
            onStartTag: (tag: Token.TagToken) => {
                if (FOREIGN_ROOTS.has(tag.tagName)) {
                    foreignDepth += tag.selfClosing ? 0 : 1
                } else if (foreignDepth === 0 && tag.tagName === 'template') {
                    templateDepth += 1
                } else if (foreignDepth === 0 && tag.tagName in TEXT_MODES) {
                    tokenizer.state = TEXT_MODES[tag.tagName]
                }
                tokenizer.inForeignNode = foreignDepth > 0
                const href = tag.tagName === 'a' ? tag.attrs.find(({ name }) => name === 'href') : undefined
                if (href && templateDepth === 0) {
                    hrefs.push(href.value)
                }
            },
            onEndTag: (tag: Token.TagToken) => {
                if (FOREIGN_ROOTS.has(tag.tagName)) {
                    foreignDepth = Math.max(0, foreignDepth - 1)
                } else if (foreignDepth === 0 && tag.tagName === 'template') {
                    templateDepth = Math.max(0, templateDepth - 1)
                }
                tokenizer.inForeignNode = foreignDepth > 0
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

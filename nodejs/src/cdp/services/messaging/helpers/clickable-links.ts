import { DefaultTreeAdapterMap, Token, Tokenizer, TokenizerMode, TreeAdapter, defaultTreeAdapter, parse } from 'parse5'

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

const TREE_ONLY_CONTENT = new Set(['svg', 'math', 'select', 'template', 'frameset'])

export const TREE_MAX_LENGTH = 1_500_000
export const TREE_MAX_DEPTH = 128
export const TREE_MAX_ELEMENTS = 500_000

type ParentNode = DefaultTreeAdapterMap['parentNode']

class TooComplexForTree extends Error {}

const ignore = (): void => {}

const scannedHrefs = (body: string): string[] | undefined => {
    const hrefs: string[] = []
    let followed = true
    const tokenizer: Tokenizer = new Tokenizer(
        {},
        {
            onStartTag: (tag: Token.TagToken) => {
                if (TREE_ONLY_CONTENT.has(tag.tagName)) {
                    followed = false
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
    return followed ? hrefs : undefined
}

const boundedTree = (body: string): ParentNode | undefined => {
    let depth = 0
    let elements = 0
    const treeAdapter: TreeAdapter<DefaultTreeAdapterMap> = {
        ...defaultTreeAdapter,
        createElement: (tagName, namespaceURI, attrs) => {
            elements += 1
            if (elements > TREE_MAX_ELEMENTS) {
                throw new TooComplexForTree()
            }
            return defaultTreeAdapter.createElement(tagName, namespaceURI, attrs)
        },
        onItemPush: () => {
            depth += 1
            if (depth > TREE_MAX_DEPTH) {
                throw new TooComplexForTree()
            }
        },
        onItemPop: () => {
            depth -= 1
        },
    }
    try {
        return parse(body, { treeAdapter })
    } catch (error) {
        if (error instanceof TooComplexForTree) {
            return undefined
        }
        throw error
    }
}

const treeHrefs = (body: string): string[] => {
    const document = body.length <= TREE_MAX_LENGTH ? boundedTree(body) : undefined
    const hrefs: string[] = []
    const parents: ParentNode[] = document ? [document] : []
    for (let parent = parents.pop(); parent; parent = parents.pop()) {
        for (const child of parent.childNodes) {
            if (!('tagName' in child)) {
                continue
            }
            const href =
                child.tagName === 'a'
                    ? (child.attrs.find(({ name, namespace }) => name === 'href' && !namespace) ??
                      child.attrs.find(({ name }) => name === 'href'))
                    : undefined
            if (href) {
                hrefs.push(href.value)
            }
            parents.push(child)
        }
    }
    return hrefs
}

export const clickableHrefs = (body: string): string[] => scannedHrefs(body) ?? treeHrefs(body)

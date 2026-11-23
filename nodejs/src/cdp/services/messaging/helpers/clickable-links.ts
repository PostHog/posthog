import {
    DefaultTreeAdapterMap,
    Parser,
    ParserOptions,
    Token,
    Tokenizer,
    TokenizerMode,
    TreeAdapter,
    defaultTreeAdapter,
} from 'parse5'

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

export const BODY_MAX_LENGTH = 1_500_000
export const UNSUBSCRIBE_TOKENS_CHECKED = 50
export const TREE_MAX_DEPTH = 128
export const TREE_MAX_ELEMENTS = 200_000
export const TREE_MAX_SCANS = 4_000_000
const TAG_MAX_ATTRIBUTES = 64

type ParentNode = DefaultTreeAdapterMap['parentNode']

class TooComplex extends Error {}

class BoundedTokenizer extends Tokenizer {
    protected override _leaveAttrName(): void {
        if ((this.currentToken as Token.TagToken).attrs.length >= TAG_MAX_ATTRIBUTES) {
            throw new TooComplex()
        }
        super._leaveAttrName()
    }
}

class BoundedParser extends Parser<DefaultTreeAdapterMap> {
    constructor(options: ParserOptions<DefaultTreeAdapterMap>) {
        super(options)
        this.tokenizer = new BoundedTokenizer(this.options, this)
    }
}

const ignore = (): void => {}

const scannedHrefs = (body: string): string[] | undefined => {
    const hrefs: string[] = []
    let followed = true
    const tokenizer: Tokenizer = new BoundedTokenizer(
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
    try {
        tokenizer.write(body, true)
    } catch (error) {
        if (error instanceof TooComplex) {
            return []
        }
        throw error
    }
    return followed ? hrefs : undefined
}

const boundedTree = (body: string): ParentNode | undefined => {
    let depth = 0
    let elements = 0
    let scans = 0
    const scan = (count: number): void => {
        scans += count
        if (scans > TREE_MAX_SCANS) {
            throw new TooComplex()
        }
    }
    const treeAdapter: TreeAdapter<DefaultTreeAdapterMap> = {
        ...defaultTreeAdapter,
        insertBefore: (parent, node, reference) => {
            scan(parent.childNodes.length)
            defaultTreeAdapter.insertBefore(parent, node, reference)
        },
        insertTextBefore: (parent, text, reference) => {
            scan(parent.childNodes.length)
            defaultTreeAdapter.insertTextBefore(parent, text, reference)
        },
        detachNode: (node) => {
            scan(node.parentNode?.childNodes.length ?? 0)
            defaultTreeAdapter.detachNode(node)
        },
        adoptAttributes: (recipient, attrs) => {
            scan(recipient.attrs.length + attrs.length)
            defaultTreeAdapter.adoptAttributes(recipient, attrs)
        },
        createElement: (tagName, namespaceURI, attrs) => {
            elements += 1
            if (elements > TREE_MAX_ELEMENTS) {
                throw new TooComplex()
            }
            return defaultTreeAdapter.createElement(tagName, namespaceURI, attrs)
        },
        onItemPush: () => {
            depth += 1
            if (depth > TREE_MAX_DEPTH) {
                throw new TooComplex()
            }
        },
        onItemPop: () => {
            depth -= 1
        },
    }
    try {
        return BoundedParser.parse(body, { treeAdapter })
    } catch (error) {
        if (error instanceof TooComplex) {
            return undefined
        }
        throw error
    }
}

const treeHrefs = (body: string): string[] => {
    const document = boundedTree(body)
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

export const isTooLargeToCheck = ({ html, text }: { html?: string; text?: string }): boolean =>
    (html?.length ?? 0) > BODY_MAX_LENGTH || (text?.length ?? 0) > BODY_MAX_LENGTH

export const clickableHrefs = (body: string): string[] =>
    body.length > BODY_MAX_LENGTH ? [] : (scannedHrefs(body) ?? treeHrefs(body))

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

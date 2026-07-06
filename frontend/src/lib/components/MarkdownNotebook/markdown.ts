import {
    NotebookBlockNode,
    NotebookComponentBlockNode,
    NotebookComponentProps,
    NotebookDocument,
    NotebookInlineMark,
    NotebookInlineNode,
    NotebookListBlockNode,
    NotebookParseError,
    NotebookTableAlignment,
    NotebookTableBlockNode,
    NotebookTableCell,
    NotebookPropValue,
    NotebookTextBlockNode,
} from './types'
import {
    createStableNodeId,
    ensureUniqueNodeIds,
    getNodeFingerprint,
    hashString,
    isNotebookPropValue,
    normalizeInlineMarks,
    normalizeInlineNodes,
} from './utils'

type BlockParseResult = {
    node: NotebookBlockNode | null
    nextLineIndex: number
    error?: NotebookParseError
}

type PropParseResult = {
    props: NotebookComponentProps
    errors: string[]
}

const COMPONENT_START_REGEX = /^<[A-Z][A-Za-z0-9]*(\s|>|\/)/
const ORDERED_LIST_REGEX = /^\s*\d+[.)](?:\s+|$)/
const BULLET_LIST_REGEX = /^\s*[-*+•](?:\s+|$)/
const LIST_ITEM_REGEX = /^(\s*)(\d+[.)]|[-*+•])(?:\s+(.*))?$/
const TASK_LIST_ITEM_REGEX = /^\[([ xX])\](?:\s+(.*))?$/
const HEADING_REGEX = /^(#{1,6})\s+(.*)$/
const IMAGE_BLOCK_REGEX = /^!\[((?:\\.|[^\]\\])*)\]\(((?:\\.|[^)\\])*)\)$/
const DIVIDER_BLOCK_REGEX = /^(?:-{3,}|\*{3,}|_{3,})$/
export const DIVIDER_COMPONENT_TAG = 'Divider'
export const COMMENT_COMPONENT_TAG = 'Comment'

/**
 * The `Comment` tag has two flavors: an authorial note (`text` prop, stored as a markdown
 * `<!-- … -->` comment) and a Google Docs-style discussion thread anchored to a `<ref>`
 * highlight (`ref` + `replies` props, stored as a real `<Comment … />` tag).
 */
export function isDiscussionCommentProps(props: NotebookComponentProps): boolean {
    return typeof props.ref === 'string' || Array.isArray(props.replies)
}
const TABLE_SEPARATOR_CELL_REGEX = /^:?-{3,}:?$/
const EMPTY_PARAGRAPH_MARKDOWN = ' '
// Every character the serializer may backslash-escape; the inline parser turns `\X` back into
// the literal character for exactly this set, so the two must stay in sync.
const INLINE_ESCAPABLE_CHARS = new Set([
    '\\',
    '`',
    '*',
    '_',
    '~',
    '[',
    ']',
    '(',
    ')',
    '<',
    '>',
    '#',
    '+',
    '-',
    '.',
    '|',
    '!',
    '•',
])
type InlineEmphasisToken = {
    token: string
    markType: 'bold' | 'italic' | 'strike'
    // Underscore emphasis must not trigger inside words (snake_case), per CommonMark
    requiresWordBoundary: boolean
}
const INLINE_EMPHASIS_TOKENS: InlineEmphasisToken[] = [
    { token: '**', markType: 'bold', requiresWordBoundary: false },
    { token: '__', markType: 'bold', requiresWordBoundary: true },
    { token: '~~', markType: 'strike', requiresWordBoundary: false },
    { token: '*', markType: 'italic', requiresWordBoundary: false },
    { token: '_', markType: 'italic', requiresWordBoundary: true },
]
// Inline tags are lowercase (HTML-style) so they can never collide with block components,
// whose tag names are required to start with an uppercase letter.
const INLINE_TAG_NAMES = ['ref', 'mention'] as const
type InlineTagName = (typeof INLINE_TAG_NAMES)[number]
const INLINE_TAG_OPEN_REGEX = /^<(ref|mention)\s+id=(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')\s*>/
let generatedNodeIdCounter = 0
const serializedNodeCache = new WeakMap<NotebookBlockNode, string>()

export function parseMarkdownNotebook(markdown: string | null | undefined): NotebookDocument {
    const lines = (markdown ?? '').replace(/\r\n?/g, '\n').split('\n')
    const nodes: NotebookBlockNode[] = []
    const errors: NotebookParseError[] = []
    const occurrences = new Map<string, number>()
    const pushParsedNode = (node: NotebookBlockNode): void => {
        const fingerprint = getNodeFingerprint(node)
        const occurrence = occurrences.get(fingerprint) ?? 0
        occurrences.set(fingerprint, occurrence + 1)
        node.id = createStableNodeId(fingerprint, occurrence)
        nodes.push(node)
    }

    let lineIndex = 0
    while (lineIndex < lines.length) {
        const line = lines[lineIndex]

        if (isEmptyParagraphPlaceholderLine(line)) {
            pushParsedNode({
                id: '',
                type: 'paragraph',
                children: [],
            })
            lineIndex += 1
            continue
        }

        if (!line.trim()) {
            lineIndex += 1
            continue
        }

        const result = parseBlock(lines, lineIndex)
        if (result.error) {
            errors.push(result.error)
        }
        if (result.node) {
            pushParsedNode(result.node)
        }
        lineIndex = Math.max(result.nextLineIndex, lineIndex + 1)
    }

    return { type: 'doc', nodes: ensureUniqueNodeIds(nodes), errors }
}

export function serializeMarkdownNotebook(document: NotebookDocument): string {
    if (document.nodes.length === 1 && isEmptyNotebookTitleNode(document.nodes[0])) {
        return ''
    }

    const shouldPreserveEmptyParagraphs = document.nodes.length > 1
    const serialized = document.nodes
        .map((node) => serializeDocumentNode(node, shouldPreserveEmptyParagraphs))
        .join('\n\n')
    const lastNode = document.nodes[document.nodes.length - 1]
    const previousNode = document.nodes[document.nodes.length - 2]
    const shouldPreserveTrailingEmptyParagraph =
        shouldPreserveEmptyParagraphs && isEmptyParagraphNode(lastNode) && previousNode?.type !== 'component'

    return shouldPreserveTrailingEmptyParagraph ? serialized : serialized.trimEnd()
}

function isEmptyNotebookTitleNode(node: NotebookBlockNode | undefined): boolean {
    return !!node && node.type === 'heading' && node.level === 1 && serializeInlineNodes(node.children) === ''
}

export function serializeNode(node: NotebookBlockNode): string {
    const cachedValue = serializedNodeCache.get(node)
    if (cachedValue !== undefined) {
        return cachedValue
    }

    const serialized = serializeNodeUncached(node)
    serializedNodeCache.set(node, serialized)
    return serialized
}

function serializeNodeUncached(node: NotebookBlockNode): string {
    if (node.type === 'heading') {
        const [firstLine, ...followingLines] = serializeInlineNodes(node.children).split('\n')
        return [`${'#'.repeat(node.level ?? 1)} ${firstLine}`, ...followingLines.map(escapeMarkdownLineStart)].join(
            '\n'
        )
    }
    if (node.type === 'paragraph') {
        return escapeMarkdownBlockLines(serializeInlineNodes(node.children))
    }
    if (node.type === 'blockquote') {
        return serializeInlineNodes(node.children)
            .split('\n')
            .map((line) => `> ${escapeMarkdownLineStart(line)}`)
            .join('\n')
    }
    if (node.type === 'list') {
        const orderedCounters: (number | undefined)[] = []
        const linePrefix = node.blockquote ? '> ' : ''
        return node.items
            .map((item) => {
                const depth = Math.max(0, item.depth)
                const ordered = item.ordered ?? node.ordered
                orderedCounters.length = depth + 1
                const start = item.start ?? (depth === 0 ? node.start : undefined) ?? 1
                const marker = ordered
                    ? `${orderedCounters[depth] === undefined ? start : orderedCounters[depth] + 1}.`
                    : '-'
                if (ordered) {
                    orderedCounters[depth] = orderedCounters[depth] === undefined ? start : orderedCounters[depth] + 1
                } else {
                    orderedCounters[depth] = undefined
                }
                const checkbox = !ordered && item.checked !== undefined ? (item.checked ? '[x] ' : '[ ] ') : ''
                return `${linePrefix}${'  '.repeat(depth)}${marker} ${checkbox}${serializeInlineNodes(
                    trimTrailingHardBreaks(item.children)
                )}`
            })
            .join('\n')
    }
    if (node.type === 'table') {
        const columnCount = getTableColumnCount(node)
        const headerCells = normalizeTableCells(node.headers, columnCount).map(serializeTableCell)
        const separatorCells = Array.from({ length: columnCount }, (_, index) =>
            serializeTableSeparatorCell(node.alignments?.[index])
        )
        const bodyRows = node.rows.map((row) => serializeTableRow(normalizeTableCells(row, columnCount)))

        return [serializeRawTableRow(headerCells), serializeRawTableRow(separatorCells), ...bodyRows].join('\n')
    }
    if (node.type === 'code') {
        // The fence must be longer than any backtick run in the content, so the content can't close it
        const fence = getCodeBlockFence(node.text)
        return `${fence}${node.language ?? ''}\n${node.text}\n${fence}`
    }
    if (node.type === 'component' && node.errors?.length && node.raw) {
        // Props that failed to parse exist only in `raw` — re-emitting from `props` would
        // silently drop the malformed source on the next save
        return node.raw
    }
    if (node.type === 'component' && node.tagName === COMMENT_COMPONENT_TAG && !isDiscussionCommentProps(node.props)) {
        return serializeCommentNode(node)
    }
    if (node.type === 'component' && node.tagName === DIVIDER_COMPONENT_TAG) {
        return '---'
    }
    if (node.type === 'component' && node.tagName === 'Image') {
        return serializeImageNode(node)
    }
    if (node.type === 'component') {
        return `<${node.tagName}${serializeComponentProps(node.props)} />`
    }
    return ''
}

function serializeDocumentNode(node: NotebookBlockNode, preserveEmptyParagraph: boolean): string {
    if (preserveEmptyParagraph && isEmptyParagraphNode(node)) {
        return EMPTY_PARAGRAPH_MARKDOWN
    }
    return serializeNode(node)
}

function isEmptyParagraphPlaceholderLine(line: string): boolean {
    return line === EMPTY_PARAGRAPH_MARKDOWN
}

function isEmptyParagraphNode(node: NotebookBlockNode | undefined): boolean {
    return !!node && node.type === 'paragraph' && node.children.length === 0
}

export function parseInlineMarkdown(markdown: string, marks: NotebookInlineMark[] = []): NotebookInlineNode[] {
    const nodes: NotebookInlineNode[] = []
    let index = 0

    const pushText = (text: string): void => {
        if (text) {
            nodes.push({ type: 'text', text, marks: marks.length ? [...marks] : undefined })
        }
    }

    while (index < markdown.length) {
        const character = markdown[index]

        if (character === '\n') {
            nodes.push({ type: 'hardBreak' })
            index += 1
            continue
        }

        if (character === '\\') {
            const nextCharacter = markdown[index + 1]
            if (nextCharacter !== undefined && INLINE_ESCAPABLE_CHARS.has(nextCharacter)) {
                pushText(nextCharacter)
                index += 2
                continue
            }
            pushText('\\')
            index += 1
            continue
        }

        const emphasis = matchEmphasisToken(markdown, index)
        if (emphasis) {
            const contentStart = index + emphasis.token.length
            const end = findEmphasisCloser(markdown, emphasis.token, contentStart, emphasis.requiresWordBoundary)
            if (end !== -1) {
                nodes.push(
                    ...parseInlineMarkdown(markdown.slice(contentStart, end), [...marks, { type: emphasis.markType }])
                )
                index = end + emphasis.token.length
                continue
            }
        }

        if (markdown.startsWith('<u>', index)) {
            const end = findTokenOutsideCodeSpans(markdown, '</u>', index + 3)
            if (end !== -1) {
                nodes.push(...parseInlineMarkdown(markdown.slice(index + 3, end), [...marks, { type: 'underline' }]))
                index = end + 4
                continue
            }
        }

        if (character === '<') {
            const inlineTag = parseInlineTag(markdown, index)
            if (inlineTag) {
                nodes.push(
                    ...parseInlineMarkdown(inlineTag.content, [...marks, { type: inlineTag.tagName, id: inlineTag.id }])
                )
                index = inlineTag.nextIndex
                continue
            }
        }

        if (character === '`') {
            const end = findUnescapedToken(markdown, '`', index + 1)
            if (end !== -1) {
                pushTextWithMarks(nodes, unescapeCodeSpanText(markdown.slice(index + 1, end)), [
                    ...marks,
                    { type: 'code' },
                ])
                index = end + 1
                continue
            }
        }

        if (character === '[') {
            const link = parseInlineLink(markdown, index)
            if (link) {
                nodes.push(
                    ...parseInlineMarkdown(
                        link.label,
                        link.href ? [...marks, { type: 'link', href: link.href }] : marks
                    )
                )
                index = link.nextIndex
                continue
            }
        }

        const nextSpecial = findNextInlineToken(markdown, index + 1)
        pushText(markdown.slice(index, nextSpecial))
        index = nextSpecial
    }

    return normalizeInlineNodes(nodes)
}

function matchEmphasisToken(markdown: string, index: number): InlineEmphasisToken | null {
    for (const emphasis of INLINE_EMPHASIS_TOKENS) {
        if (!markdown.startsWith(emphasis.token, index)) {
            continue
        }
        // A single `*`/`_` immediately followed by the same character is a doubled delimiter
        // whose closer was not found — treat it as literal rather than nesting into it.
        if (emphasis.token.length === 1 && markdown[index + 1] === emphasis.token) {
            continue
        }
        const contentStart = markdown[index + emphasis.token.length]
        if (contentStart === undefined || /\s/.test(contentStart)) {
            continue
        }
        if (emphasis.requiresWordBoundary && isAsciiAlphaNumeric(markdown[index - 1])) {
            continue
        }
        return emphasis
    }
    return null
}

function findEmphasisCloser(markdown: string, token: string, fromIndex: number, requiresWordBoundary: boolean): number {
    let searchIndex = fromIndex
    while (searchIndex < markdown.length) {
        const position = findTokenOutsideCodeSpans(markdown, token, searchIndex)
        if (position === -1) {
            return -1
        }

        const previousCharacter = markdown[position - 1]
        const followingCharacter = markdown[position + token.length]
        if (
            position > fromIndex &&
            previousCharacter !== undefined &&
            !/\s/.test(previousCharacter) &&
            (!requiresWordBoundary || !isAsciiAlphaNumeric(followingCharacter))
        ) {
            return position
        }
        searchIndex = position + 1
    }
    return -1
}

// Code spans bind tighter than other inline constructs — a token inside `...` doesn't count.
// Consumes complete code spans before the candidate and re-searches after them.
function findTokenOutsideCodeSpans(markdown: string, token: string, fromIndex: number): number {
    let searchIndex = fromIndex
    while (searchIndex < markdown.length) {
        const position = findUnescapedToken(markdown, token, searchIndex)
        if (position === -1) {
            return -1
        }

        const codeStart = findUnescapedToken(markdown, '`', searchIndex)
        if (codeStart !== -1 && codeStart < position) {
            const codeEnd = findUnescapedToken(markdown, '`', codeStart + 1)
            if (codeEnd !== -1) {
                searchIndex = codeEnd + 1
                continue
            }
        }

        return position
    }
    return -1
}

function findUnescapedToken(markdown: string, token: string, fromIndex: number): number {
    let position = markdown.indexOf(token, fromIndex)
    while (position !== -1) {
        let backslashCount = 0
        while (markdown[position - backslashCount - 1] === '\\') {
            backslashCount += 1
        }
        if (backslashCount % 2 === 0) {
            return position
        }
        position = markdown.indexOf(token, position + 1)
    }
    return -1
}

function parseInlineLink(
    markdown: string,
    index: number
): { label: string; href: string | null; nextIndex: number } | null {
    const labelEnd = findTokenOutsideCodeSpans(markdown, '](', index + 1)
    if (labelEnd === -1) {
        return null
    }

    // Hrefs may contain backslash-escaped characters and balanced parentheses (Wikipedia-style URLs)
    let cursor = labelEnd + 2
    let parenDepth = 0
    let rawHref = ''
    while (cursor < markdown.length) {
        const character = markdown[cursor]
        if (
            character === '\\' &&
            markdown[cursor + 1] !== undefined &&
            INLINE_ESCAPABLE_CHARS.has(markdown[cursor + 1])
        ) {
            rawHref += markdown[cursor + 1]
            cursor += 2
            continue
        }
        if (character === ')') {
            if (parenDepth === 0) {
                return {
                    label: markdown.slice(index + 1, labelEnd),
                    href: sanitizeNotebookLinkHref(rawHref),
                    nextIndex: cursor + 1,
                }
            }
            parenDepth -= 1
        }
        if (character === '(') {
            parenDepth += 1
        }
        rawHref += character
        cursor += 1
    }
    return null
}

/**
 * Parses an inline tag (`<ref id="x">…</ref>`, `<mention id="5">…</mention>`) at `index`.
 * A tag without a well-formed opener or matching closer is not a tag — the text stays
 * literal, so nothing a user types can ever be swallowed.
 */
function parseInlineTag(
    markdown: string,
    index: number
): { tagName: InlineTagName; id: string; content: string; nextIndex: number } | null {
    const openMatch = markdown.slice(index).match(INLINE_TAG_OPEN_REGEX)
    if (!openMatch) {
        return null
    }

    const tagName = openMatch[1] as InlineTagName
    const id = (openMatch[2] ?? openMatch[3] ?? '').replace(/\\(.)/g, '$1')
    const contentStart = index + openMatch[0].length
    const closeToken = `</${tagName}>`
    const end = findTokenOutsideCodeSpans(markdown, closeToken, contentStart)
    if (end === -1 || !id) {
        return null
    }

    return {
        tagName,
        id,
        content: markdown.slice(contentStart, end),
        nextIndex: end + closeToken.length,
    }
}

function isAsciiAlphaNumeric(character: string | undefined): boolean {
    return !!character && /[A-Za-z0-9]/.test(character)
}

export function serializeInlineNodes(nodes: NotebookInlineNode[]): string {
    return nodes.map(serializeInlineNode).join('')
}

export function htmlElementToInlineNodes(element: HTMLElement): NotebookInlineNode[] {
    return normalizeInlineNodes(htmlChildNodesToInlineNodes(element, []))
}

export function inlineNodesToHtml(nodes: NotebookInlineNode[]): string {
    return nodes.map(inlineNodeToHtml).join('')
}

export function sanitizeNotebookLinkHref(href: string): string | null {
    const trimmedHref = href.trim()
    if (!/^https?:\/\/\S+$/i.test(trimmedHref)) {
        return null
    }

    try {
        const url = new URL(trimmedHref)
        return url.protocol === 'http:' || url.protocol === 'https:' ? trimmedHref : null
    } catch {
        return null
    }
}

function parseBlock(lines: string[], lineIndex: number): BlockParseResult {
    const line = lines[lineIndex]
    const trimmed = line.trim()

    if (trimmed.startsWith('```')) {
        return parseCodeBlock(lines, lineIndex)
    }

    if (IMAGE_BLOCK_REGEX.test(trimmed)) {
        return parseImageBlock(lines, lineIndex)
    }

    if (DIVIDER_BLOCK_REGEX.test(trimmed)) {
        return {
            node: { id: '', type: 'component', tagName: DIVIDER_COMPONENT_TAG, props: {} },
            nextLineIndex: lineIndex + 1,
        }
    }

    if (trimmed.startsWith('<!--')) {
        const commentEndLineIndex = getCommentBlockEndLine(lines, lineIndex)
        if (commentEndLineIndex !== null) {
            return parseCommentBlock(lines, lineIndex, commentEndLineIndex)
        }
    }

    if (COMPONENT_START_REGEX.test(trimmed)) {
        return parseComponentBlock(lines, lineIndex)
    }

    const headingMatch = line.match(HEADING_REGEX)
    if (headingMatch) {
        return {
            node: {
                id: '',
                type: 'heading',
                level: headingMatch[1].length as NotebookTextBlockNode['level'],
                children: parseInlineMarkdown(headingMatch[2]),
            },
            nextLineIndex: lineIndex + 1,
        }
    }

    if (isTableStart(lines, lineIndex)) {
        return parseTableBlock(lines, lineIndex)
    }

    if (ORDERED_LIST_REGEX.test(line) || BULLET_LIST_REGEX.test(line)) {
        return parseListBlock(lines, lineIndex)
    }

    if (trimmed.startsWith('>')) {
        if (isListLine(stripBlockquoteMarker(line))) {
            return parseBlockquotedListBlock(lines, lineIndex)
        }

        const quoteLines: string[] = []
        let nextLineIndex = lineIndex
        while (
            nextLineIndex < lines.length &&
            lines[nextLineIndex].trim().startsWith('>') &&
            !isListLine(stripBlockquoteMarker(lines[nextLineIndex]))
        ) {
            quoteLines.push(stripBlockquoteMarker(lines[nextLineIndex]))
            nextLineIndex += 1
        }
        return {
            node: {
                id: '',
                type: 'blockquote',
                children: parseInlineMarkdown(quoteLines.join('\n')),
            },
            nextLineIndex,
        }
    }

    return parseParagraphBlock(lines, lineIndex)
}

function parseParagraphBlock(lines: string[], lineIndex: number): BlockParseResult {
    const paragraphLines: string[] = []
    let nextLineIndex = lineIndex

    while (nextLineIndex < lines.length) {
        const line = lines[nextLineIndex]
        const trimmed = line.trim()
        if (
            !trimmed ||
            trimmed.startsWith('```') ||
            IMAGE_BLOCK_REGEX.test(trimmed) ||
            DIVIDER_BLOCK_REGEX.test(trimmed) ||
            (trimmed.startsWith('<!--') && getCommentBlockEndLine(lines, nextLineIndex) !== null) ||
            COMPONENT_START_REGEX.test(trimmed) ||
            HEADING_REGEX.test(line) ||
            isTableStart(lines, nextLineIndex) ||
            ORDERED_LIST_REGEX.test(line) ||
            BULLET_LIST_REGEX.test(line) ||
            trimmed.startsWith('>')
        ) {
            break
        }
        paragraphLines.push(line)
        nextLineIndex += 1
    }

    return {
        node: {
            id: '',
            type: 'paragraph',
            children: parseInlineMarkdown(paragraphLines.join('\n')),
        },
        nextLineIndex,
    }
}

function isListLine(line: string): boolean {
    return ORDERED_LIST_REGEX.test(line) || BULLET_LIST_REGEX.test(line)
}

function stripBlockquoteMarker(line: string): string {
    return line.trim().replace(/^>\s?/, '')
}

function parseBlockquotedListBlock(lines: string[], lineIndex: number): BlockParseResult {
    const listLines: string[] = []
    let nextLineIndex = lineIndex
    while (nextLineIndex < lines.length) {
        const line = lines[nextLineIndex]
        if (!line.trim().startsWith('>') || !isListLine(stripBlockquoteMarker(line))) {
            break
        }
        listLines.push(stripBlockquoteMarker(line))
        nextLineIndex += 1
    }

    const result = parseListBlock(listLines, 0)
    return {
        node: { ...result.node, blockquote: true } as NotebookListBlockNode,
        nextLineIndex: lineIndex + result.nextLineIndex,
    }
}

function parseListBlock(lines: string[], lineIndex: number): BlockParseResult {
    const ordered = ORDERED_LIST_REGEX.test(lines[lineIndex])
    const items: NotebookListBlockNode['items'] = []
    let nextLineIndex = lineIndex

    while (nextLineIndex < lines.length) {
        const line = lines[nextLineIndex]
        const listItem = parseListItemLine(line, nextLineIndex - lineIndex)
        if (!listItem) {
            break
        }
        items.push(listItem)
        nextLineIndex += 1
    }

    // External markdown indents nested items by 2-4 spaces (or marker width); clamp each item
    // to at most one level deeper than the previous so 4-space nesting doesn't double the depth
    let previousDepth = -1
    for (const item of items) {
        item.depth = Math.min(item.depth, previousDepth + 1)
        previousDepth = item.depth
    }

    return {
        node: {
            id: '',
            type: 'list',
            ordered,
            start: ordered ? items.find((item) => item.depth === 0 && item.ordered)?.start : undefined,
            items,
        },
        nextLineIndex,
    }
}

function parseListItemLine(line: string, listItemIndex: number): NotebookListBlockNode['items'][number] | null {
    const match = line.match(LIST_ITEM_REGEX)
    if (!match) {
        return null
    }

    const orderedMatch = match[2].match(/^(\d+)[.)]$/)
    // GFM task markers only apply to bullet items — `1. [x]` stays literal text
    const taskMatch = orderedMatch ? null : (match[3] ?? '').match(TASK_LIST_ITEM_REGEX)

    return {
        id: createStableNodeId(`list-item:${String(listItemIndex)}:${line}`, 0),
        children: parseInlineMarkdown(taskMatch ? (taskMatch[2] ?? '') : (match[3] ?? '')),
        depth: getListItemDepth(match[1]),
        ordered: orderedMatch !== null,
        start: orderedMatch ? Number(orderedMatch[1]) : undefined,
        checked: taskMatch ? taskMatch[1].toLowerCase() === 'x' : undefined,
    }
}

function getListItemDepth(indentation: string): number {
    const columns = [...indentation].reduce((total, character) => total + (character === '\t' ? 4 : 1), 0)
    return Math.floor(columns / 2)
}

function isTableStart(lines: string[], lineIndex: number): boolean {
    // Require a leading pipe so prose that merely contains a `|` can't become a table header
    if (!(lines[lineIndex] ?? '').trim().startsWith('|')) {
        return false
    }

    const headerCells = splitMarkdownTableRow(lines[lineIndex] ?? '')
    const separatorCells = splitMarkdownTableRow(lines[lineIndex + 1] ?? '')

    return headerCells.length >= 1 && separatorCells.length >= 1 && separatorCells.every(isTableSeparatorCell)
}

function parseTableBlock(lines: string[], lineIndex: number): BlockParseResult {
    const headers = splitMarkdownTableRow(lines[lineIndex]).map(parseTableCell)
    const alignments = splitMarkdownTableRow(lines[lineIndex + 1]).map(parseTableAlignment)
    const rows: NotebookTableBlockNode['rows'] = []
    let nextLineIndex = lineIndex + 2

    while (nextLineIndex < lines.length) {
        // Rows must start with a pipe — a following paragraph containing a `|` is not a row
        if (!lines[nextLineIndex].trim().startsWith('|')) {
            break
        }
        const cells = splitMarkdownTableRow(lines[nextLineIndex])
        if (cells.length < 1) {
            break
        }
        rows.push(cells.map(parseTableCell))
        nextLineIndex += 1
    }

    return {
        node: {
            id: '',
            type: 'table',
            headers,
            rows,
            alignments,
        },
        nextLineIndex,
    }
}

function splitMarkdownTableRow(line: string): string[] {
    if (!line.includes('|')) {
        return []
    }

    const cells: string[] = []
    let cell = ''
    let source = line.trim()
    if (source.startsWith('|')) {
        source = source.slice(1)
    }
    if (source.endsWith('|')) {
        source = source.slice(0, -1)
    }

    for (let index = 0; index < source.length; index++) {
        const character = source[index]
        if (character === '\\' && source[index + 1] === '|') {
            cell += '|'
            index += 1
            continue
        }
        if (character === '|') {
            cells.push(cell.trim())
            cell = ''
            continue
        }
        cell += character
    }
    cells.push(cell.trim())

    return cells
}

function isTableSeparatorCell(cell: string): boolean {
    return TABLE_SEPARATOR_CELL_REGEX.test(cell.trim())
}

function parseTableAlignment(cell: string): NotebookTableAlignment | undefined {
    const trimmedCell = cell.trim()
    const alignsLeft = trimmedCell.startsWith(':')
    const alignsRight = trimmedCell.endsWith(':')
    if (alignsLeft && alignsRight) {
        return 'center'
    }
    if (alignsLeft) {
        return 'left'
    }
    if (alignsRight) {
        return 'right'
    }
    return undefined
}

function parseTableCell(cell: string): NotebookTableCell {
    return { children: parseInlineMarkdown(cell) }
}

function getTableColumnCount(node: NotebookTableBlockNode): number {
    return Math.max(1, node.headers.length, node.alignments?.length ?? 0, ...node.rows.map((row) => row.length))
}

function normalizeTableCells(cells: NotebookTableCell[], columnCount: number): NotebookTableCell[] {
    return Array.from({ length: columnCount }, (_, index) => cells[index] ?? { children: [] })
}

function serializeTableRow(cells: NotebookTableCell[]): string {
    return serializeRawTableRow(cells.map(serializeTableCell))
}

function serializeRawTableRow(cells: string[]): string {
    return `| ${cells.join(' | ')} |`
}

function serializeTableCell(cell: NotebookTableCell): string {
    // Pipes in plain text are already escaped by escapeInlineMarkdownText; this pass only
    // covers pipes inside code spans (skipping `\X` pairs so they aren't double-escaped)
    return serializeInlineNodes(trimTrailingHardBreaks(cell.children))
        .replace(/\\[\s\S]|\|/g, (match) => (match === '|' ? '\\|' : match))
        .replace(/\n/g, ' ')
}

function serializeTableSeparatorCell(alignment: NotebookTableAlignment | undefined): string {
    if (alignment === 'left') {
        return ':---'
    }
    if (alignment === 'center') {
        return ':---:'
    }
    if (alignment === 'right') {
        return '---:'
    }
    return '---'
}

function parseCodeBlock(lines: string[], lineIndex: number): BlockParseResult {
    const startLine = lines[lineIndex].trim()
    const fenceLength = startLine.match(/^`+/)?.[0].length ?? 3
    // Only a bare fence at least as long as the opener closes the block, so shorter
    // fences (or fences with info strings) inside the code stay part of the content
    const closingFenceRegex = new RegExp(`^\`{${fenceLength},}$`)
    const language = startLine.slice(fenceLength).trim() || undefined
    const codeLines: string[] = []
    let nextLineIndex = lineIndex + 1

    while (nextLineIndex < lines.length && !closingFenceRegex.test(lines[nextLineIndex].trim())) {
        codeLines.push(lines[nextLineIndex])
        nextLineIndex += 1
    }

    return {
        node: {
            id: '',
            type: 'code',
            language,
            text: codeLines.join('\n'),
        },
        nextLineIndex: nextLineIndex < lines.length ? nextLineIndex + 1 : nextLineIndex,
        error:
            nextLineIndex >= lines.length
                ? {
                      message: 'Unclosed code block',
                      raw: lines.slice(lineIndex).join('\n'),
                      line: lineIndex + 1,
                  }
                : undefined,
    }
}

/**
 * A comment block is `<!--` … `-->` where the closing marker ends its line; when `-->`
 * has trailing content (or never appears) the text stays a paragraph so nothing is
 * ever swallowed. Comments may span lines, including blank ones.
 */
function getCommentBlockEndLine(lines: string[], lineIndex: number): number | null {
    for (let index = lineIndex; index < lines.length; index++) {
        const trimmed = lines[index].trim()
        const markerIndex = trimmed.indexOf('-->', index === lineIndex ? 4 : 0)
        if (markerIndex !== -1) {
            return markerIndex === trimmed.length - 3 ? index : null
        }
    }
    return null
}

function parseCommentBlock(lines: string[], lineIndex: number, endLineIndex: number): BlockParseResult {
    const raw = lines
        .slice(lineIndex, endLineIndex + 1)
        .join('\n')
        .trim()
    const text = raw.slice(4, raw.length - 3).trim()

    return {
        node: { id: '', type: 'component', tagName: COMMENT_COMPONENT_TAG, props: { text } },
        nextLineIndex: endLineIndex + 1,
    }
}

function serializeCommentNode(node: NotebookComponentBlockNode): string {
    const text = typeof node.props.text === 'string' ? node.props.text : ''
    // `-->` inside the text would close the comment early, so it is broken apart
    const safeText = text.replace(/-->/g, '-- >').trim()
    return `<!-- ${safeText} -->`
}

function parseImageBlock(lines: string[], lineIndex: number): BlockParseResult {
    const match = lines[lineIndex].trim().match(IMAGE_BLOCK_REGEX)

    return {
        node: {
            id: '',
            type: 'component',
            tagName: 'Image',
            props: {
                alt: unescapeMarkdownImageValue(match?.[1] ?? ''),
                src: unescapeMarkdownImageValue(match?.[2] ?? ''),
            },
        },
        nextLineIndex: lineIndex + 1,
    }
}

function parseComponentBlock(lines: string[], lineIndex: number): BlockParseResult {
    const rawLines: string[] = []
    const firstLine = lines[lineIndex].trim()
    const tagName = firstLine.match(/^<([A-Z][A-Za-z0-9]*)/)?.[1]
    let nextLineIndex = lineIndex
    let foundTerminator = false

    // Components are block-level: a blank line ends the scan so an unterminated tag can
    // never swallow the rest of the document
    while (nextLineIndex < lines.length && (nextLineIndex === lineIndex || lines[nextLineIndex].trim())) {
        rawLines.push(lines[nextLineIndex])
        const raw = rawLines.join('\n').trim()
        if (raw.endsWith('/>') || (tagName && raw.includes(`</${tagName}>`))) {
            foundTerminator = true
            break
        }
        nextLineIndex += 1
    }

    const raw = rawLines.join('\n').trim()
    if (!foundTerminator) {
        return {
            node: makeComponentFallbackParagraph(raw),
            nextLineIndex,
            error: { message: 'Unclosed component tag', raw, line: lineIndex + 1 },
        }
    }

    const parsed = parseComponentTag(raw)
    return {
        // A malformed tag degrades to a paragraph holding the raw source — source text must
        // never be dropped from the node tree, or the next save destroys it
        node: parsed.node ?? makeComponentFallbackParagraph(raw),
        nextLineIndex: nextLineIndex + 1,
        error: parsed.error ? { ...parsed.error, line: lineIndex + 1 } : undefined,
    }
}

function makeComponentFallbackParagraph(raw: string): NotebookTextBlockNode {
    const children: NotebookInlineNode[] = []
    raw.split('\n').forEach((line, index) => {
        if (index > 0) {
            children.push({ type: 'hardBreak' })
        }
        if (line) {
            children.push({ type: 'text', text: line })
        }
    })

    return {
        id: '',
        type: 'paragraph',
        children: normalizeInlineNodes(children),
    }
}

function parseComponentTag(raw: string): { node: NotebookComponentBlockNode | null; error?: NotebookParseError } {
    const match = raw.match(/^<([A-Z][A-Za-z0-9]*)([\s\S]*?)(?:\/>|>[\s\S]*<\/\1>)$/)
    if (!match) {
        return {
            node: null,
            error: {
                message: 'Invalid notebook component tag',
                raw,
                line: 0,
            },
        }
    }

    const propParseResult = parseComponentProps(match[2] ?? '')
    return {
        node: {
            id: '',
            type: 'component',
            tagName: match[1],
            props: propParseResult.props,
            raw,
            errors: propParseResult.errors.length ? propParseResult.errors : undefined,
        },
    }
}

function parseComponentProps(source: string): PropParseResult {
    const props: NotebookComponentProps = {}
    const errors: string[] = []
    let index = 0

    while (index < source.length) {
        while (/\s/.test(source[index] ?? '')) {
            index += 1
        }
        if (index >= source.length) {
            break
        }

        const nameMatch = source.slice(index).match(/^([A-Za-z_][A-Za-z0-9_-]*)/)
        if (!nameMatch) {
            errors.push(`Could not parse props near: ${source.slice(index, index + 24)}`)
            break
        }

        const name = nameMatch[1]
        index += name.length
        while (/\s/.test(source[index] ?? '')) {
            index += 1
        }

        if (source[index] !== '=') {
            props[name] = true
            continue
        }

        index += 1
        while (/\s/.test(source[index] ?? '')) {
            index += 1
        }

        const parsedValue = readPropValue(source, index)
        index = parsedValue.nextIndex

        if (parsedValue.error) {
            errors.push(parsedValue.error)
            continue
        }

        if (isNotebookPropValue(parsedValue.value)) {
            props[name] = parsedValue.value
        } else {
            errors.push(`Unsupported value for prop "${name}"`)
        }
    }

    return { props, errors }
}

function readPropValue(source: string, index: number): { value: unknown; nextIndex: number; error?: string } {
    const firstChar = source[index]

    if (firstChar === '"' || firstChar === "'") {
        const quote = firstChar
        let nextIndex = index + 1
        let value = ''
        while (nextIndex < source.length) {
            const char = source[nextIndex]
            if (char === '\\' && nextIndex + 1 < source.length) {
                value += source[nextIndex + 1]
                nextIndex += 2
                continue
            }
            if (char === quote) {
                if (quote === '"') {
                    try {
                        const parsedValue = JSON.parse(source.slice(index, nextIndex + 1))
                        if (typeof parsedValue === 'string') {
                            return { value: decodeHtmlEntities(parsedValue), nextIndex: nextIndex + 1 }
                        }
                    } catch {
                        // Fall through to the permissive parser for legacy hand-written values.
                    }
                }
                return { value: decodeHtmlEntities(value), nextIndex: nextIndex + 1 }
            }
            value += char
            nextIndex += 1
        }
        return { value: null, nextIndex, error: 'Unclosed quoted prop value' }
    }

    if (firstChar === '{') {
        const balanced = readBalancedExpression(source, index)
        if (!balanced) {
            return { value: null, nextIndex: source.length, error: 'Unclosed expression prop value' }
        }
        return {
            value: parseExpressionValue(balanced.value),
            nextIndex: balanced.nextIndex,
        }
    }

    const rawMatch = source.slice(index).match(/^([^\s/>]+)/)
    const raw = rawMatch?.[1] ?? ''
    return {
        value: parseExpressionValue(raw),
        nextIndex: index + raw.length,
    }
}

function readBalancedExpression(source: string, index: number): { value: string; nextIndex: number } | null {
    let depth = 0
    let nextIndex = index
    let quote: string | null = null

    while (nextIndex < source.length) {
        const char = source[nextIndex]
        const previousChar = source[nextIndex - 1]

        if (quote) {
            if (char === quote && previousChar !== '\\') {
                quote = null
            }
            nextIndex += 1
            continue
        }

        if (char === '"' || char === "'") {
            quote = char
            nextIndex += 1
            continue
        }

        if (char === '{') {
            depth += 1
        }
        if (char === '}') {
            depth -= 1
            if (depth === 0) {
                return {
                    value: source.slice(index, nextIndex + 1),
                    nextIndex: nextIndex + 1,
                }
            }
        }
        nextIndex += 1
    }

    return null
}

function parseExpressionValue(raw: string): unknown {
    const trimmed = raw.trim()
    const unwrapped = trimmed.startsWith('{') && trimmed.endsWith('}') ? trimmed.slice(1, -1).trim() : trimmed

    if (unwrapped === 'true') {
        return true
    }
    if (unwrapped === 'false') {
        return false
    }
    if (unwrapped === 'null') {
        return null
    }
    if (/^-?\d+(\.\d+)?$/.test(unwrapped)) {
        return Number(unwrapped)
    }

    try {
        return JSON.parse(unwrapped)
    } catch {
        return trimmed
    }
}

function serializeComponentProps(props: NotebookComponentProps): string {
    const serialized = getOrderedComponentPropEntries(getSerializableComponentProps(props))
        .filter(([, value]) => value !== undefined)
        .map(([key, value]) => (value === true ? ` ${key}` : ` ${key}=${serializePropValue(value)}`))
        .join('')
    return serialized
}

function getSerializableComponentProps(props: NotebookComponentProps): NotebookComponentProps {
    const nextProps = Object.entries(props).reduce<NotebookComponentProps>((accumulator, [key, value]) => {
        if (key !== 'view' && key !== 'edit' && key !== 'hideFilters' && key !== 'hideResults') {
            accumulator[key] = value
        }
        return accumulator
    }, {})
    const legacyViewPanelVisible = typeof props.view === 'boolean' ? props.view : undefined
    const legacyEditPanelVisible = typeof props.edit === 'boolean' ? props.edit : undefined
    const hideFilters = typeof props.hideFilters === 'boolean' ? props.hideFilters : legacyEditPanelVisible === false
    const hideResults = typeof props.hideResults === 'boolean' ? props.hideResults : legacyViewPanelVisible === false

    if (hideFilters) {
        nextProps.hideFilters = true
    }
    if (hideResults) {
        nextProps.hideResults = true
    }

    return nextProps
}

function getOrderedComponentPropEntries(props: NotebookComponentProps): [string, NotebookPropValue][] {
    const entries = Object.entries(props)
    const orderedKeys = ['hideFilters', 'hideResults']
    return [
        ...orderedKeys.flatMap((key): [string, NotebookPropValue][] =>
            Object.prototype.hasOwnProperty.call(props, key) ? [[key, props[key]]] : []
        ),
        ...entries.filter(([key]) => !orderedKeys.includes(key)),
    ]
}

function serializePropValue(value: NotebookPropValue): string {
    if (typeof value === 'string') {
        return JSON.stringify(value)
    }
    if (typeof value === 'number' || typeof value === 'boolean' || value === null) {
        return `{${String(value)}}`
    }
    return `{${JSON.stringify(value)}}`
}

function serializeImageNode(node: NotebookComponentBlockNode): string {
    const src = typeof node.props.src === 'string' ? node.props.src : ''
    const alt = typeof node.props.alt === 'string' ? node.props.alt : ''

    return `![${escapeMarkdownImageAlt(alt)}](${escapeMarkdownImageSrc(src)})`
}

// Browsers keep a trailing placeholder <br> in edited lines; it is presentational, so it must not
// become a line break in single-line markdown contexts.
function trimTrailingHardBreaks(nodes: NotebookInlineNode[]): NotebookInlineNode[] {
    let end = nodes.length
    while (end > 0 && nodes[end - 1].type === 'hardBreak') {
        end -= 1
    }
    return end === nodes.length ? nodes : nodes.slice(0, end)
}

function serializeInlineNode(node: NotebookInlineNode): string {
    if (node.type === 'hardBreak') {
        return '\n'
    }

    const marks = normalizeInlineMarks(node.marks ?? [])
    const isCodeText = marks.some((mark) => mark.type === 'code')
    const escapedText = isCodeText ? escapeCodeSpanText(node.text) : escapeInlineMarkdownText(node.text)

    return marks.reduce((text, mark) => wrapInlineText(text, mark, marks), escapedText)
}

function wrapInlineText(text: string, mark: NotebookInlineMark, marks: NotebookInlineMark[]): string {
    // `***text***` is ambiguous to parse — bold+italic is emitted as `**_text_**` in one step
    // (outer `**` has no word-boundary rules; the inner `_` is safely flanked by `*`)
    const hasBoldAndItalic =
        marks.some((otherMark) => otherMark.type === 'bold') && marks.some((otherMark) => otherMark.type === 'italic')
    if (mark.type === 'bold') {
        return hasBoldAndItalic
            ? wrapInlineEmphasis(wrapInlineEmphasis(text, '_'), '**')
            : wrapInlineEmphasis(text, '**')
    }
    if (mark.type === 'italic') {
        return hasBoldAndItalic ? text : wrapInlineEmphasis(text, '*')
    }
    if (mark.type === 'underline') {
        return `<u>${text}</u>`
    }
    if (mark.type === 'strike') {
        return wrapInlineEmphasis(text, '~~')
    }
    if (mark.type === 'code') {
        return `\`${text}\``
    }
    if (mark.type === 'ref' || mark.type === 'mention') {
        return mark.id ? `<${mark.type} id=${JSON.stringify(mark.id)}>${text}</${mark.type}>` : text
    }
    const href = sanitizeNotebookLinkHref(mark.href)
    return href ? `[${text}](${escapeMarkdownLinkHref(href)})` : text
}

// Emphasis delimiters are not recognized next to whitespace, so boundary whitespace is
// hoisted outside the delimiters (`*core* ` instead of `* core *`)
function wrapInlineEmphasis(text: string, delimiter: string): string {
    const leading = text.match(/^\s*/)?.[0] ?? ''
    const trailing = text.length > leading.length ? (text.match(/\s*$/)?.[0] ?? '') : ''
    const core = text.slice(leading.length, text.length - trailing.length)
    if (!core) {
        return text
    }
    return `${leading}${delimiter}${core}${delimiter}${trailing}`
}

function pushTextWithMarks(nodes: NotebookInlineNode[], text: string, marks: NotebookInlineMark[]): void {
    if (text) {
        nodes.push({ type: 'text', text, marks: marks.length ? marks : undefined })
    }
}

function findNextInlineToken(markdown: string, startIndex: number): number {
    const indexes = ['\\', '**', '*', '__', '_', '<u>', '<ref', '<mention', '~~', '`', '[', '\n']
        .map((token) => markdown.indexOf(token, startIndex))
        .filter((index) => index !== -1)
    return indexes.length ? Math.min(...indexes) : markdown.length
}

function htmlChildNodesToInlineNodes(parent: HTMLElement, marks: NotebookInlineMark[]): NotebookInlineNode[] {
    const children: NotebookInlineNode[] = []

    parent.childNodes.forEach((child) => {
        if (isBlockBreakElement(child) && children.length && children[children.length - 1]?.type !== 'hardBreak') {
            children.push({ type: 'hardBreak' })
        }

        children.push(...htmlNodeToInlineNodes(child, marks))
    })

    return children
}

function htmlNodeToInlineNodes(node: ChildNode, marks: NotebookInlineMark[]): NotebookInlineNode[] {
    if (node.nodeType === Node.TEXT_NODE) {
        return node.textContent
            ? [{ type: 'text', text: node.textContent, marks: marks.length ? marks : undefined }]
            : []
    }

    if (!(node instanceof HTMLElement)) {
        return []
    }

    const tagName = node.tagName.toLowerCase()
    if (tagName === 'br') {
        return [{ type: 'hardBreak' }]
    }

    const nextMarks = [...marks]
    if (tagName === 'strong' || tagName === 'b') {
        nextMarks.push({ type: 'bold' })
    }
    if (tagName === 'em' || tagName === 'i') {
        nextMarks.push({ type: 'italic' })
    }
    if (tagName === 'u') {
        nextMarks.push({ type: 'underline' })
    }
    if (tagName === 's' || tagName === 'del' || tagName === 'strike') {
        nextMarks.push({ type: 'strike' })
    }
    if (tagName === 'code') {
        nextMarks.push({ type: 'code' })
    }
    if (tagName === 'a') {
        const href = sanitizeNotebookLinkHref(node.getAttribute('href') ?? '')
        if (href) {
            nextMarks.push({ type: 'link', href })
        }
    }
    if (tagName === 'span') {
        const refId = node.getAttribute('data-notebook-ref')
        if (refId) {
            nextMarks.push({ type: 'ref', id: refId })
        }
        const mentionId = node.getAttribute('data-notebook-mention')
        if (mentionId) {
            nextMarks.push({ type: 'mention', id: mentionId })
        }
    }

    const children = htmlChildNodesToInlineNodes(node, nextMarks)

    if (isBlockBreakElement(node)) {
        children.push({ type: 'hardBreak' })
    }

    return children
}

function isBlockBreakElement(node: ChildNode): node is HTMLElement {
    if (!(node instanceof HTMLElement)) {
        return false
    }

    const tagName = node.tagName.toLowerCase()
    return tagName === 'div' || tagName === 'p'
}

function inlineNodeToHtml(node: NotebookInlineNode): string {
    if (node.type === 'hardBreak') {
        return '<br>'
    }

    return normalizeInlineMarks(node.marks ?? []).reduce(
        (html, mark) => wrapHtmlText(html, mark),
        escapeHtml(node.text)
    )
}

function wrapHtmlText(html: string, mark: NotebookInlineMark): string {
    if (mark.type === 'bold') {
        return `<strong>${html}</strong>`
    }
    if (mark.type === 'italic') {
        return `<em>${html}</em>`
    }
    if (mark.type === 'underline') {
        return `<u>${html}</u>`
    }
    if (mark.type === 'strike') {
        return `<s>${html}</s>`
    }
    if (mark.type === 'code') {
        return `<code>${html}</code>`
    }
    if (mark.type === 'ref') {
        return `<span class="MarkdownNotebook__ref" data-notebook-ref="${escapeAttribute(mark.id)}">${html}</span>`
    }
    if (mark.type === 'mention') {
        return `<span class="MarkdownNotebook__mention" data-notebook-mention="${escapeAttribute(mark.id)}">${html}</span>`
    }
    const href = sanitizeNotebookLinkHref(mark.href)
    return href ? `<a href="${escapeAttribute(href)}">${html}</a>` : html
}

// Escapes every character sequence the inline parser would interpret, so that
// parse(serialize(doc)) preserves literal user text exactly. Mirrored by the `\` branch
// in parseInlineMarkdown via INLINE_ESCAPABLE_CHARS.
export function escapeInlineMarkdownText(text: string): string {
    return text
        .replace(/[\\`*[\]|]/g, (match) => `\\${match}`)
        .replace(/~~+/g, (run) => '\\~'.repeat(run.length))
        .replace(/_/g, (_match, offset: number, source: string) =>
            // Intraword underscores (snake_case) are never emphasis, keep them readable
            isAsciiAlphaNumeric(source[offset - 1]) && isAsciiAlphaNumeric(source[offset + 1]) ? '_' : '\\_'
        )
        .replace(/<(?=\/?(?:u>|ref[\s>]|mention[\s>]))/g, '\\<')
}

export function escapeCodeSpanText(text: string): string {
    return text.replace(/[\\`]/g, (match) => `\\${match}`)
}

function unescapeCodeSpanText(text: string): string {
    return text.replace(/\\([\\`])/g, '$1')
}

function escapeMarkdownLinkHref(href: string): string {
    return href.replace(/[\\()]/g, (match) => `\\${match}`)
}

export function escapeMarkdownBlockLines(serialized: string): string {
    return serialized.split('\n').map(escapeMarkdownLineStart).join('\n')
}

// Prevents a serialized text line from being re-parsed as a different block type
// (heading, list, blockquote, divider, component). Inline-level characters (backtick,
// `*`, `[`, `|`) are already escaped by escapeInlineMarkdownText.
export function escapeMarkdownLineStart(line: string): string {
    const leadingWhitespace = line.match(/^\s*/)?.[0] ?? ''
    const content = line.slice(leadingWhitespace.length)

    const orderedListMatch = content.match(/^(\d+)([.)])(\s|$)/)
    if (orderedListMatch) {
        return `${leadingWhitespace}${orderedListMatch[1]}\\${content.slice(orderedListMatch[1].length)}`
    }

    if (/^(#{1,6}\s|>|[-+•](\s|$)|-{3,}\s*$|<[A-Z]|<!--)/.test(content)) {
        return `${leadingWhitespace}\\${content}`
    }

    return line
}

function getCodeBlockFence(text: string): string {
    const longestRun = Math.max(0, ...Array.from(text.matchAll(/`+/g), (match) => match[0].length))
    return '`'.repeat(Math.max(3, longestRun + 1))
}

function escapeMarkdownImageAlt(text: string): string {
    return text.replace(/\\/g, '\\\\').replace(/\]/g, '\\]')
}

function escapeMarkdownImageSrc(text: string): string {
    return text.replace(/\\/g, '\\\\').replace(/\)/g, '\\)')
}

function unescapeMarkdownImageValue(text: string): string {
    return text.replace(/\\([\\\])])/g, '$1')
}

// Both escapes mirror the browser's HTML fragment serialization exactly: the editor compares
// generated HTML against live `innerHTML` to decide whether the DOM needs syncing, and any byte
// difference forces a rewrite that destroys the caret mid-typing.
function escapeHtml(text: string): string {
    return text
        .replace(/&/g, '&amp;')
        .replace(/\u00a0/g, '&nbsp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
}

function escapeAttribute(text: string): string {
    return text
        .replace(/&/g, '&amp;')
        .replace(/\u00a0/g, '&nbsp;')
        .replace(/"/g, '&quot;')
}

function decodeHtmlEntities(text: string): string {
    return text
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&apos;/g, "'")
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&')
}

export function makeEmptyParagraph(idSeed: string = 'empty'): NotebookTextBlockNode {
    const node: NotebookTextBlockNode = {
        id: '',
        type: 'paragraph',
        children: [],
    }
    node.id = makeGeneratedMarkdownId(idSeed)
    return node
}

export function makeListItemId(idSeed: string = 'list-item'): string {
    return makeGeneratedMarkdownId(idSeed)
}

function makeGeneratedMarkdownId(idSeed: string): string {
    const id = createStableNodeId(
        `${idSeed}:${hashString(`${String(Date.now())}:${String(generatedNodeIdCounter)}`)}`,
        0
    )
    generatedNodeIdCounter += 1
    return id
}

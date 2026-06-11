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
const HEADING_REGEX = /^(#{1,6})\s+(.*)$/
const IMAGE_BLOCK_REGEX = /^!\[((?:\\.|[^\]\\])*)\]\(((?:\\.|[^)\\])*)\)$/
const DIVIDER_BLOCK_REGEX = /^(?:-{3,}|\*{3,}|_{3,})$/
export const DIVIDER_COMPONENT_TAG = 'Divider'
const TABLE_SEPARATOR_CELL_REGEX = /^:?-{3,}:?$/
const EMPTY_PARAGRAPH_MARKDOWN = ' '
let generatedNodeIdCounter = 0

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

export function serializeNode(node: NotebookBlockNode): string {
    if (node.type === 'heading') {
        return `${'#'.repeat(node.level ?? 1)} ${serializeInlineNodes(node.children)}`
    }
    if (node.type === 'paragraph') {
        return serializeInlineNodes(node.children)
    }
    if (node.type === 'blockquote') {
        return serializeInlineNodes(node.children)
            .split('\n')
            .map((line) => `> ${line}`)
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
                return `${linePrefix}${'  '.repeat(depth)}${marker} ${serializeInlineNodes(
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
        return `\`\`\`${node.language ?? ''}\n${node.text}\n\`\`\``
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
        const unescapedText = unescapeMarkdownText(text)
        if (unescapedText) {
            nodes.push({ type: 'text', text: unescapedText, marks: marks.length ? [...marks] : undefined })
        }
    }

    while (index < markdown.length) {
        if (markdown[index] === '\n') {
            nodes.push({ type: 'hardBreak' })
            index += 1
            continue
        }

        if (markdown.startsWith('**', index)) {
            const end = markdown.indexOf('**', index + 2)
            if (end !== -1) {
                nodes.push(...parseInlineMarkdown(markdown.slice(index + 2, end), [...marks, { type: 'bold' }]))
                index = end + 2
                continue
            }
        }

        if (markdown.startsWith('<u>', index)) {
            const end = markdown.indexOf('</u>', index + 3)
            if (end !== -1) {
                nodes.push(...parseInlineMarkdown(markdown.slice(index + 3, end), [...marks, { type: 'underline' }]))
                index = end + 4
                continue
            }
        }

        if (markdown.startsWith('~~', index)) {
            const end = markdown.indexOf('~~', index + 2)
            if (end !== -1) {
                nodes.push(...parseInlineMarkdown(markdown.slice(index + 2, end), [...marks, { type: 'strike' }]))
                index = end + 2
                continue
            }
        }

        if (markdown[index] === '`') {
            const end = markdown.indexOf('`', index + 1)
            if (end !== -1) {
                pushTextWithMarks(nodes, markdown.slice(index + 1, end), [...marks, { type: 'code' }])
                index = end + 1
                continue
            }
        }

        if (markdown[index] === '[') {
            const labelEnd = markdown.indexOf('](', index)
            if (labelEnd !== -1) {
                const hrefEnd = markdown.indexOf(')', labelEnd + 2)
                if (hrefEnd !== -1) {
                    const href = sanitizeNotebookLinkHref(markdown.slice(labelEnd + 2, hrefEnd))
                    nodes.push(
                        ...parseInlineMarkdown(
                            markdown.slice(index + 1, labelEnd),
                            href ? [...marks, { type: 'link', href }] : marks
                        )
                    )
                    index = hrefEnd + 1
                    continue
                }
            }
        }

        if (markdown[index] === '*' && !markdown.startsWith('**', index)) {
            const end = markdown.indexOf('*', index + 1)
            if (end !== -1) {
                nodes.push(...parseInlineMarkdown(markdown.slice(index + 1, end), [...marks, { type: 'italic' }]))
                index = end + 1
                continue
            }
        }

        const nextSpecial = findNextInlineToken(markdown, index + 1)
        pushText(markdown.slice(index, nextSpecial))
        index = nextSpecial
    }

    return normalizeInlineNodes(nodes)
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

    return {
        id: createStableNodeId(`list-item:${String(listItemIndex)}:${line}`, 0),
        children: parseInlineMarkdown(match[3] ?? ''),
        depth: getListItemDepth(match[1]),
        ordered: orderedMatch !== null,
        start: orderedMatch ? Number(orderedMatch[1]) : undefined,
    }
}

function getListItemDepth(indentation: string): number {
    const columns = [...indentation].reduce((total, character) => total + (character === '\t' ? 4 : 1), 0)
    return Math.floor(columns / 2)
}

function isTableStart(lines: string[], lineIndex: number): boolean {
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
    return serializeInlineNodes(trimTrailingHardBreaks(cell.children)).replace(/\|/g, '\\|').replace(/\n/g, ' ')
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
    const language = startLine.slice(3).trim() || undefined
    const codeLines: string[] = []
    let nextLineIndex = lineIndex + 1

    while (nextLineIndex < lines.length && !lines[nextLineIndex].trim().startsWith('```')) {
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

    while (nextLineIndex < lines.length) {
        rawLines.push(lines[nextLineIndex])
        const raw = rawLines.join('\n').trim()
        if (raw.endsWith('/>') || (tagName && raw.includes(`</${tagName}>`))) {
            break
        }
        nextLineIndex += 1
    }

    const raw = rawLines.join('\n').trim()
    const parsed = parseComponentTag(raw)
    return {
        node: parsed.node,
        nextLineIndex: nextLineIndex + 1,
        error: parsed.error ? { ...parsed.error, line: lineIndex + 1 } : undefined,
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

    return normalizeInlineMarks(node.marks ?? []).reduce(
        (text, mark) => wrapInlineText(text, mark),
        escapeMarkdownText(node.text)
    )
}

function wrapInlineText(text: string, mark: NotebookInlineMark): string {
    if (mark.type === 'bold') {
        return `**${text}**`
    }
    if (mark.type === 'italic') {
        return `*${text}*`
    }
    if (mark.type === 'underline') {
        return `<u>${text}</u>`
    }
    if (mark.type === 'strike') {
        return `~~${text}~~`
    }
    if (mark.type === 'code') {
        return `\`${text.replace(/`/g, '\\`')}\``
    }
    const href = sanitizeNotebookLinkHref(mark.href)
    return href ? `[${text}](${href})` : text
}

function pushTextWithMarks(nodes: NotebookInlineNode[], text: string, marks: NotebookInlineMark[]): void {
    if (text) {
        nodes.push({ type: 'text', text, marks: marks.length ? marks : undefined })
    }
}

function findNextInlineToken(markdown: string, startIndex: number): number {
    const indexes = ['**', '*', '<u>', '~~', '`', '[', '\n']
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
    const href = sanitizeNotebookLinkHref(mark.href)
    return href ? `<a href="${escapeAttribute(href)}">${html}</a>` : html
}

function escapeMarkdownText(text: string): string {
    return text.replace(/\\/g, '\\\\')
}

function unescapeMarkdownText(text: string): string {
    return text.replace(/\\\\/g, '\\')
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

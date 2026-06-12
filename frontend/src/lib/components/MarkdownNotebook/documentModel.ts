import { RestoreInlineSelectionRequest, RestoreSelectionRequest } from './editorTypes'
import { removeInlineRefMark } from './inlineContent'
import {
    COMMENT_COMPONENT_TAG,
    DIVIDER_COMPONENT_TAG,
    isDiscussionCommentProps,
    makeEmptyParagraph,
    makeListItemId,
    parseMarkdownNotebook,
    serializeMarkdownNotebook,
} from './markdown'
import { getTableCellAtPosition, getTableEdgeCellPosition } from './tableModel'
import { getTextChanges, mapTextIndex } from './textChanges'
import {
    NotebookBlockNode,
    NotebookComponentBlockNode,
    NotebookDocument,
    NotebookInlineNode,
    NotebookListBlockNode,
    NotebookPropValue,
    NotebookTextBlockNode,
} from './types'
import { cloneNotebookNode, ensureUniqueNodeIds, getInlineText } from './utils'

export function getNotebookObjectProp(
    value: NotebookPropValue | undefined
): Record<string, NotebookPropValue> | undefined {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return undefined
    }
    return value
}

export function getNotebookStringProp(value: NotebookPropValue | undefined): string | undefined {
    return typeof value === 'string' ? value : undefined
}

export type MarkdownNotebookTextSurface = 'text' | 'quote' | 'code' | 'comment'

export type MarkdownNotebookVisualGroup =
    | {
          type: 'text'
          key: string
          items: { node: NotebookBlockNode; index: number; surface: MarkdownNotebookTextSurface }[]
      }
    | {
          type: 'block'
          key: string
          node: NotebookBlockNode
          index: number
      }

export function getMarkdownNotebookVisualGroups(
    nodes: NotebookBlockNode[],
    insertMenuNodeId?: string
): MarkdownNotebookVisualGroup[] {
    const groups: MarkdownNotebookVisualGroup[] = []
    let currentTextGroup: Extract<MarkdownNotebookVisualGroup, { type: 'text' }> | null = null
    const isTextLikeNode = (node: NotebookBlockNode | undefined): boolean =>
        !!node && (isTextBlockNode(node) || node.type === 'list' || node.type === 'code')

    // A discussion comment sits right above the text it highlights; joining the surrounding
    // text group keeps that text from being split into separate cards. A comment anchored to
    // a standalone block (a component) stays its own row.
    const commentJoinsTextGroup = (index: number): boolean => {
        if (!isDiscussionCommentNode(nodes[index])) {
            return false
        }
        if (currentTextGroup) {
            return true
        }
        let nextIndex = index + 1
        while (nextIndex < nodes.length && isDiscussionCommentNode(nodes[nextIndex])) {
            nextIndex += 1
        }
        return isTextLikeNode(nodes[nextIndex])
    }

    nodes.forEach((node, index) => {
        if ((isTextLikeNode(node) || commentJoinsTextGroup(index)) && node.id !== insertMenuNodeId) {
            if (!currentTextGroup) {
                currentTextGroup = {
                    type: 'text',
                    key: `text-${node.id}`,
                    items: [],
                }
                groups.push(currentTextGroup)
            }

            currentTextGroup.items.push({
                node,
                index,
                surface: isDiscussionCommentNode(node)
                    ? 'comment'
                    : node.type === 'code'
                      ? 'code'
                      : isGroupedBlockquoteNode(node)
                        ? 'quote'
                        : 'text',
            })
            return
        }

        currentTextGroup = null
        groups.push({
            type: 'block',
            key: node.id,
            node,
            index,
        })
    })

    return groups
}

export function isTextBlockNode(node: NotebookBlockNode): node is NotebookTextBlockNode {
    return node.type === 'paragraph' || node.type === 'heading' || node.type === 'blockquote'
}

export function isGroupedBlockquoteNode(
    node: NotebookBlockNode
): node is NotebookTextBlockNode | NotebookListBlockNode {
    return (isTextBlockNode(node) && node.type === 'blockquote') || (node.type === 'list' && !!node.blockquote)
}

export function isPromptComponentNode(node: NotebookBlockNode): node is NotebookComponentBlockNode {
    return node.type === 'component' && node.tagName === 'Prompt'
}

export function isDividerComponentNode(node: NotebookBlockNode): node is NotebookComponentBlockNode {
    return node.type === 'component' && node.tagName === DIVIDER_COMPONENT_TAG
}

/**
 * A discussion comment is a `<Comment>` carrying human replies (and usually a `ref`
 * anchor), as opposed to an authorial note which carries only `text` and serializes as a
 * markdown `<!-- … -->` comment.
 */
export function isDiscussionCommentNode(node: NotebookBlockNode): node is NotebookComponentBlockNode {
    return isCommentComponentNode(node) && isDiscussionCommentProps(node.props)
}

export function getDiscussionCommentRefId(node: NotebookBlockNode): string | null {
    if (!isCommentComponentNode(node)) {
        return null
    }
    const refId = node.props.ref
    return typeof refId === 'string' && refId.trim() ? refId : null
}

function mapNodeInlineChildren(
    node: NotebookBlockNode,
    mapChildren: (children: NotebookInlineNode[]) => NotebookInlineNode[]
): NotebookBlockNode {
    if (isTextBlockNode(node)) {
        const children = mapChildren(node.children)
        return children === node.children ? node : { ...node, children }
    }
    if (node.type === 'list') {
        let didChange = false
        const items = node.items.map((item) => {
            const children = mapChildren(item.children)
            if (children === item.children) {
                return item
            }
            didChange = true
            return { ...item, children }
        })
        return didChange ? { ...node, items } : node
    }
    if (node.type === 'table') {
        let didChange = false
        const mapCell = (cell: { children: NotebookInlineNode[] }): { children: NotebookInlineNode[] } => {
            const children = mapChildren(cell.children)
            if (children === cell.children) {
                return cell
            }
            didChange = true
            return { ...cell, children }
        }
        const headers = node.headers.map(mapCell)
        const rows = node.rows.map((row) => row.map(mapCell))
        return didChange ? { ...node, headers, rows } : node
    }
    return node
}

/**
 * Deletes blocks and, for any deleted discussion comment with a `ref` anchor, unwraps the
 * matching `<ref>` tags so no orphaned highlight is left behind. The reverse direction is
 * intentionally asymmetric: removing a ref never deletes the comment — it holds people's
 * replies and stays anchored to the right until deleted on its own.
 */
export function removeNotebookNodesWithRefCleanup(document: NotebookDocument, nodeIds: Set<string>): NotebookDocument {
    const removedRefIds = new Set(
        document.nodes
            .filter((node) => nodeIds.has(node.id))
            .map(getDiscussionCommentRefId)
            .filter((refId): refId is string => !!refId)
    )
    const remainingNodes = document.nodes.filter((node) => !nodeIds.has(node.id))
    return { ...document, nodes: stripNotebookRefMarksFromNodes(remainingNodes, removedRefIds) }
}

/** Unwraps `<ref>` tags with the given ids across every text-bearing block, keeping the text. */
export function stripNotebookRefMarksFromNodes(nodes: NotebookBlockNode[], refIds: Set<string>): NotebookBlockNode[] {
    if (!refIds.size) {
        return nodes
    }

    return nodes.map((node) =>
        mapNodeInlineChildren(node, (children) =>
            [...refIds].reduce((current, refId) => removeInlineRefMark(current, refId), children)
        )
    )
}

export function isCommentComponentNode(node: NotebookBlockNode): node is NotebookComponentBlockNode {
    return node.type === 'component' && node.tagName === COMMENT_COMPONENT_TAG
}

export function getPromptSource(value: NotebookPropValue | undefined): 'slash' | 'selection' {
    return value === 'selection' ? 'selection' : 'slash'
}

export function textBlocksShareContinuationStyle(left: NotebookTextBlockNode, right: NotebookTextBlockNode): boolean {
    if (left.type !== right.type) {
        return false
    }

    return left.type !== 'heading' || (left.level ?? 1) === (right.level ?? 1)
}

export function isInlineInsertMenuRow(node: NotebookBlockNode | undefined, insertMenuNodeId?: string): boolean {
    if (!node || !isTextBlockNode(node)) {
        return false
    }

    if (node.id === insertMenuNodeId) {
        return true
    }

    const text = getInlineText(node.children)
    return !text.trim() || getSlashCommandQuery(text) !== null
}

export function isBlankInsertMenuButtonRow(node: NotebookBlockNode | undefined): boolean {
    if (!node || !isTextBlockNode(node)) {
        return false
    }

    return !getInlineText(node.children).trim()
}

export function getInlineInsertMenuQuery(node: NotebookBlockNode): string {
    if (!isTextBlockNode(node)) {
        return ''
    }

    return getSlashCommandQuery(getInlineText(node.children)) ?? ''
}

export function getSlashCommandQuery(text: string): string | null {
    return text.startsWith('/') ? text.slice(1) : null
}

export function getTitlePasteParts(markdown: string): {
    titleMarkdown: string
    bodyMarkdown: string
    hasBodyMarkdown: boolean
} {
    const normalizedMarkdown = markdown.replace(/\r\n?/g, '\n')
    const firstLineBreakIndex = normalizedMarkdown.indexOf('\n')
    if (firstLineBreakIndex === -1) {
        return { titleMarkdown: normalizedMarkdown, bodyMarkdown: '', hasBodyMarkdown: false }
    }

    return {
        titleMarkdown: normalizedMarkdown.slice(0, firstLineBreakIndex),
        bodyMarkdown: normalizedMarkdown.slice(firstLineBreakIndex + 1),
        hasBodyMarkdown: true,
    }
}

export function getTitleChildrenFromMarkdownLine(markdown: string): NotebookInlineNode[] {
    const firstNode = parseMarkdownNotebook(markdown).nodes[0]
    if (firstNode && isTextBlockNode(firstNode)) {
        return firstNode.children
    }

    return markdown ? [{ type: 'text', text: markdown }] : []
}

export function normalizeNotebookTitlePasteBodyNode(node: NotebookBlockNode): NotebookBlockNode {
    if (!isTextBlockNode(node)) {
        return node
    }

    return {
        ...node,
        type: 'paragraph',
        level: undefined,
    }
}

export function getListShortcut(text: string): { ordered: boolean; start?: number } | null {
    const normalizedText = text.replace(/\u00a0/g, ' ')
    const orderedMatch = normalizedText.match(/^(\d+)[.)]\s*$/)
    if (orderedMatch) {
        return { ordered: true, start: Number(orderedMatch[1]) }
    }

    if (/^[-*+•]\s+$/.test(normalizedText)) {
        return { ordered: false }
    }

    return null
}

export type TextBlockShortcutReplacement = {
    nodes: NotebookBlockNode[]
    restoreSelection: RestoreSelectionRequest
}

export function getTextBlockShortcutReplacement(
    node: NotebookTextBlockNode,
    isTitleBlock: boolean,
    text: string
): TextBlockShortcutReplacement | null {
    const headingShortcut = isTitleBlock
        ? null
        : getHeadingShortcut(text, node.type === 'heading' ? (node.level ?? 1) : null)
    if (headingShortcut !== null) {
        return {
            nodes: [
                {
                    id: node.id,
                    type: 'heading',
                    level: headingShortcut,
                    children: [],
                },
            ],
            restoreSelection: { nodeId: node.id, start: 0, end: 0 },
        }
    }

    if (isTitleBlock || node.type !== 'paragraph') {
        return null
    }

    if (getBlockquoteShortcut(text)) {
        return {
            nodes: [
                {
                    id: node.id,
                    type: 'blockquote',
                    children: [],
                },
            ],
            restoreSelection: { nodeId: node.id, start: 0, end: 0 },
        }
    }

    if (getCodeBlockShortcut(text)) {
        return {
            nodes: [
                {
                    id: node.id,
                    type: 'code',
                    text: '',
                },
            ],
            restoreSelection: { nodeId: node.id, start: 0, end: 0 },
        }
    }

    if (getDividerShortcut(text)) {
        const trailingParagraph = makeEmptyParagraph(`divider-${node.id}`)
        return {
            nodes: [
                {
                    id: node.id,
                    type: 'component',
                    tagName: DIVIDER_COMPONENT_TAG,
                    props: {},
                },
                trailingParagraph,
            ],
            restoreSelection: { nodeId: trailingParagraph.id, start: 0, end: 0 },
        }
    }

    const listShortcut = getListShortcut(text)
    if (listShortcut) {
        const listItemId = makeListItemId(`shortcut-${node.id}`)
        return {
            nodes: [
                {
                    id: node.id,
                    type: 'list',
                    ordered: listShortcut.ordered,
                    start: listShortcut.start,
                    items: [
                        {
                            id: listItemId,
                            children: [],
                            depth: 0,
                            ordered: listShortcut.ordered,
                            start: listShortcut.start,
                        },
                    ],
                },
            ],
            restoreSelection: { nodeId: node.id, listItemIndex: 0, listItemId, start: 0, end: 0 },
        }
    }

    return null
}

export function getHeadingShortcut(text: string, currentLevel: number | null): 1 | 2 | 3 | null {
    if (!/^#{1,3}\s?$/.test(text)) {
        return null
    }

    const markerLevel = text.trim().length
    const nextLevel = currentLevel === null ? markerLevel : currentLevel + markerLevel

    return Math.min(3, Math.max(1, nextLevel)) as 1 | 2 | 3
}

export function getBlockquoteShortcut(text: string): boolean {
    return /^>\s?$/.test(text)
}

export function getCodeBlockShortcut(text: string): boolean {
    return /^```\s?$/.test(text)
}

export function getDividerShortcut(text: string): boolean {
    return /^-{3}\s?$/.test(text)
}

export function ensureEditableNotebookDocument(document: NotebookDocument): NotebookDocument {
    let nodes = document.nodes.length ? [...document.nodes] : [makeEmptyNotebookTitle('notebook-title')]
    let didChange = nodes.length !== document.nodes.length

    // The `# ` title row always stays first: discussion comments that end up above it (a
    // comment on the title itself, a merge, a manual markdown edit) slide below it instead
    // of pushing a fresh empty title on top of the document.
    let leadingCommentCount = 0
    while (leadingCommentCount < nodes.length && isDiscussionCommentNode(nodes[leadingCommentCount])) {
        leadingCommentCount += 1
    }
    if (leadingCommentCount > 0 && leadingCommentCount < nodes.length && isTextBlockNode(nodes[leadingCommentCount])) {
        nodes = [
            nodes[leadingCommentCount],
            ...nodes.slice(0, leadingCommentCount),
            ...nodes.slice(leadingCommentCount + 1),
        ]
        didChange = true
    }

    const firstNode = nodes[0]

    if (isTextBlockNode(firstNode)) {
        if (firstNode.type !== 'heading' || firstNode.level !== 1) {
            nodes[0] = {
                ...firstNode,
                type: 'heading',
                level: 1,
            }
            didChange = true
        }
    } else {
        nodes.unshift(makeEmptyNotebookTitle('notebook-title'))
        didChange = true
    }

    const uniqueNodes = ensureUniqueNodeIds(nodes)
    if (uniqueNodes !== nodes) {
        didChange = true
    }

    return didChange ? { ...document, nodes: uniqueNodes } : document
}

export function makeEmptyNotebookTitle(idSeed: string): NotebookTextBlockNode {
    return {
        ...makeEmptyParagraph(idSeed),
        type: 'heading',
        level: 1,
    }
}

export function areNotebookDocumentsEqual(left: NotebookDocument, right: NotebookDocument): boolean {
    return JSON.stringify(left) === JSON.stringify(right)
}

/**
 * Re-map a captured caret through a document change (a remote merge or external value
 * update), so the caret stays at the same place in the text instead of at the same
 * numeric offset — when a collaborator inserts at the start of the line you're editing,
 * your caret at the end must move with the text.
 */
export function mapRestoreSelectionThroughDocumentChange(
    request: RestoreSelectionRequest | null,
    previousDocument: NotebookDocument,
    nextDocument: NotebookDocument
): RestoreSelectionRequest | null {
    if (!request || !('nodeId' in request)) {
        return request
    }

    const previousNode = previousDocument.nodes.find((node) => node.id === request.nodeId)
    const nextNode = nextDocument.nodes.find((node) => node.id === request.nodeId)
    if (!previousNode || !nextNode) {
        return request
    }

    const previousText = getEditableTextForSelectionRequest(previousNode, request)
    const nextText = getEditableTextForSelectionRequest(nextNode, request)
    if (previousText === null || nextText === null || previousText === nextText) {
        return request
    }

    const changes = getTextChanges(previousText, nextText)
    return {
        ...request,
        start: mapTextIndex(request.start, changes, 'right'),
        end: mapTextIndex(request.end, changes, 'right'),
    }
}

function getEditableTextForSelectionRequest(
    node: NotebookBlockNode,
    request: RestoreInlineSelectionRequest
): string | null {
    if (request.tableCell !== undefined) {
        if (node.type !== 'table') {
            return null
        }
        const cell = getTableCellAtPosition(node, request.tableCell)
        return cell ? getInlineText(cell.children) : null
    }

    if (node.type === 'list') {
        const item =
            (request.listItemId !== undefined
                ? node.items.find((candidate) => candidate.id === request.listItemId)
                : undefined) ?? (request.listItemIndex !== undefined ? node.items[request.listItemIndex] : undefined)
        return item ? getInlineText(item.children) : null
    }

    if (isTextBlockNode(node)) {
        return getInlineText(node.children)
    }

    if (node.type === 'code') {
        return node.text
    }

    return null
}

export function getHistoryRestoreSelection(document: NotebookDocument): RestoreSelectionRequest | null {
    for (const node of document.nodes) {
        if (isTextBlockNode(node)) {
            const offset = getInlineText(node.children).length
            return { nodeId: node.id, start: offset, end: offset }
        }

        if (node.type === 'list' && node.items[0]) {
            const offset = getInlineText(node.items[0].children).length
            return { nodeId: node.id, listItemIndex: 0, listItemId: node.items[0].id, start: offset, end: offset }
        }

        if (node.type === 'table') {
            const firstPosition = getTableEdgeCellPosition(node, 'next')
            const cell = firstPosition ? getTableCellAtPosition(node, firstPosition) : undefined
            if (firstPosition) {
                const offset = getInlineText(cell?.children ?? []).length
                return { nodeId: node.id, tableCell: firstPosition, start: offset, end: offset }
            }
        }

        if (node.type === 'component') {
            return { nodeId: node.id, start: 0, end: 0 }
        }
    }

    return null
}

export function hasNotebookContent(nodes: NotebookBlockNode[]): boolean {
    return nodes.some(nodeHasContent)
}

export function nodeHasContent(node: NotebookBlockNode): boolean {
    if (isTextBlockNode(node)) {
        return getInlineText(node.children).trim().length > 0
    }
    if (node.type === 'list') {
        return node.items.some((item) => getInlineText(item.children).trim().length > 0)
    }
    if (node.type === 'table') {
        return [...node.headers, ...node.rows.flat()].some((cell) => getInlineText(cell.children).trim().length > 0)
    }
    if (node.type === 'code') {
        return node.text.trim().length > 0
    }
    return true
}

export function serializeNotebookNodes(nodes: NotebookBlockNode[]): string {
    return serializeMarkdownNotebook({ type: 'doc', nodes, errors: [] })
}

export function getAskAISelectionQuery(selectedMarkdown: string, userQuery: string, chatId: string): string {
    const highlightedMarkdown = selectedMarkdown.trim()
    // A fence longer than any backtick run in the content, so embedded ``` can't close the block early
    const longestBacktickRun = highlightedMarkdown.match(/`+/g)?.reduce((max, run) => Math.max(max, run.length), 0) ?? 0
    const fence = '`'.repeat(Math.max(3, longestBacktickRun + 1))

    return [
        'The user highlighted content in a markdown notebook and asked PostHog AI to help with it.',
        '',
        'User request:',
        userQuery,
        '',
        'Highlighted markdown:',
        `${fence}markdown`,
        highlightedMarkdown,
        fence,
        '',
        `Use the notebook context as the source of truth. The inline <Chat id="${chatId}" /> block is the answer anchor directly below the highlighted content.`,
        'If the user asks to replace, rewrite, shorten, expand, summarize, or otherwise change the highlighted content, update the notebook near the highlighted content and keep that Chat block as the anchor for the answer.',
        'If the user asks to explain or analyze the highlighted content, answer directly without editing the notebook unless they explicitly ask for a change.',
    ].join('\n')
}

export function setClipboardMarkdown(clipboardData: DataTransfer, markdown: string): void {
    clipboardData.setData('text/plain', markdown)
    clipboardData.setData('text/markdown', markdown)
}

export function getClipboardMarkdown(clipboardData: DataTransfer): string {
    return clipboardData.getData('text/markdown') || clipboardData.getData('text/plain')
}

export function setsEqual(left: Set<string>, right: Set<string>): boolean {
    if (left.size !== right.size) {
        return false
    }

    for (const value of left) {
        if (!right.has(value)) {
            return false
        }
    }

    return true
}

export function writeSystemClipboardText(markdown: string): void {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
        return
    }

    void navigator.clipboard.writeText(markdown).catch(() => {})
}

export async function readSystemClipboardText(): Promise<string | null> {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.readText) {
        return null
    }

    try {
        return await navigator.clipboard.readText()
    } catch {
        return null
    }
}

export function shouldUseMarkdownPaste(plainText: string, html: string, parsedDocument: NotebookDocument): boolean {
    if (!plainText.trim() || !parsedDocument.nodes.length) {
        return false
    }

    if (!html) {
        return true
    }

    if (parsedDocument.nodes.length !== 1) {
        return true
    }

    const [node] = parsedDocument.nodes
    return node.type !== 'paragraph' || hasInlineMarkdownSyntax(plainText)
}

export function hasInlineMarkdownSyntax(value: string): boolean {
    return /(\*\*[^*]+\*\*|`[^`]+`|<u>[\s\S]+<\/u>|\[[^\]]+\]\([^)]+\)|(^|[^*])\*[^*\s][^*]*\*|~~[^~]+~~|(^|[^A-Za-z0-9])_[^\s_][^_]*_(?![A-Za-z0-9]))/.test(
        value
    )
}

export function rekeyNotebookNodes(nodes: NotebookBlockNode[], seed: string): NotebookBlockNode[] {
    return nodes.map((node, index) => {
        const clonedNode = cloneNotebookNode(node)
        const id = makeEmptyParagraph(`${seed}-${String(index)}`).id

        if (clonedNode.type === 'list') {
            return {
                ...clonedNode,
                id,
                items: clonedNode.items.map((item, itemIndex) => ({
                    ...item,
                    id: makeListItemId(`${seed}-${String(index)}-${String(itemIndex)}`),
                })),
            }
        }

        return {
            ...clonedNode,
            id,
        }
    })
}

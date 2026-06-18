import { parseMarkdownNotebook, serializeMarkdownNotebook } from './markdown'
import type { NotebookBlockNode, NotebookComponentBlockNode, NotebookPropValue } from './types'
import { getNodeFingerprint, getNodeSignature, getNodeText } from './utils'

export const NOTEBOOK_AI_WRITING_PLACEHOLDER = 'Thinking...'
const NOTEBOOK_PROMPT_COMPONENT_TAG = 'Prompt'

export type NotebookAIResponseMarkdownResult = {
    markdown: string
    responseNodeIndex: number
}

export function replaceNotebookAIResponseMarkdown(
    markdown: string,
    responseNodeIndex: number,
    replacementMarkdown: string,
    replacedNodeCount: number = 1
): NotebookAIResponseMarkdownResult {
    return applyNotebookAIResponseMarkdown(markdown, responseNodeIndex, replacementMarkdown, replacedNodeCount)
}

export function insertNotebookAIFollowUpPromptAfterResponse(
    markdown: string,
    responseNodeIndex: number,
    promptMarkdown: string
): string {
    const trimmedPromptMarkdown = promptMarkdown.trim()
    if (!trimmedPromptMarkdown) {
        return markdown
    }

    const document = parseMarkdownNotebook(markdown)
    if (responseNodeIndex < 0 || responseNodeIndex >= document.nodes.length) {
        return markdown
    }

    const promptNodes = parseMarkdownNotebook(trimmedPromptMarkdown).nodes
    if (!promptNodes.length) {
        return markdown
    }
    if (promptNodes.some(isEmptyNotebookPromptNode) && document.nodes.some(isEmptyNotebookPromptNode)) {
        return markdown
    }

    const insertionIndex = responseNodeIndex + 1
    const nextNodes = [
        ...document.nodes.slice(0, insertionIndex),
        ...promptNodes,
        ...document.nodes.slice(insertionIndex),
    ]

    return serializeMarkdownNotebook({
        ...document,
        nodes: nextNodes,
    })
}

function isEmptyNotebookPromptNode(node: NotebookBlockNode): node is NotebookComponentBlockNode {
    return (
        node.type === 'component' &&
        node.tagName === NOTEBOOK_PROMPT_COMPONENT_TAG &&
        isEmptyNotebookStringProp(node.props.question) &&
        isEmptyNotebookStringProp(node.props.selectedMarkdown) &&
        isEmptyNotebookStringProp(node.props.ref)
    )
}

function isEmptyNotebookStringProp(value: NotebookPropValue | undefined): boolean {
    if (typeof value === 'string') {
        return !value.trim()
    }

    return value === undefined
}

function applyNotebookAIResponseMarkdown(
    markdown: string,
    responseNodeIndex: number,
    insertedMarkdown: string,
    replacedNodeCount: number = 1
): NotebookAIResponseMarkdownResult {
    const trimmedInsertedMarkdown = normalizeNotebookAIInsertedMarkdown(insertedMarkdown).trim()
    if (!trimmedInsertedMarkdown) {
        return { markdown, responseNodeIndex }
    }

    const document = parseMarkdownNotebook(markdown)
    if (responseNodeIndex < 0 || responseNodeIndex >= document.nodes.length) {
        return { markdown, responseNodeIndex }
    }

    const parsedReplacementNodes = parseMarkdownNotebook(trimmedInsertedMarkdown).nodes
    if (!parsedReplacementNodes.length) {
        return { markdown, responseNodeIndex }
    }

    const replacementNodes = stripEchoedNotebookContextBeforeAIResponse(
        document.nodes,
        responseNodeIndex,
        parsedReplacementNodes
    )
    if (!replacementNodes.length) {
        return { markdown, responseNodeIndex }
    }
    const targetRange = getNotebookAIResponseReplaceRange(responseNodeIndex, replacedNodeCount)
    const { insertionIndex, deleteCount } = targetRange
    const nextNodes = [
        ...document.nodes.slice(0, insertionIndex),
        ...replacementNodes,
        ...document.nodes.slice(insertionIndex + deleteCount),
    ]
    const nextResponseNodeIndex = insertionIndex + replacementNodes.length - 1

    return {
        markdown: serializeMarkdownNotebook({
            ...document,
            nodes: nextNodes,
        }),
        responseNodeIndex: nextResponseNodeIndex,
    }
}

function normalizeNotebookAIInsertedMarkdown(markdown: string): string {
    return markdown
        .replace(
            /(^|\n)<insight>\s*([A-Za-z0-9_-]+)\s*<\/insight>(?=\n|$)/gi,
            (_match, prefix: string, shortId: string) => `${prefix}${getSavedInsightQueryMarkdown(shortId)}`
        )
        .replace(
            /(^|\n)<Insight\s+(?:id|shortId)=["']([A-Za-z0-9_-]+)["']\s*\/>(?=\n|$)/g,
            (_match, prefix: string, shortId: string) => `${prefix}${getSavedInsightQueryMarkdown(shortId)}`
        )
}

function getSavedInsightQueryMarkdown(shortId: string): string {
    return `<Query query={{"kind":"SavedInsightNode","shortId":"${shortId}"}} />`
}

function stripEchoedNotebookContextBeforeAIResponse(
    currentNodes: NotebookBlockNode[],
    cursorIndex: number,
    replacementNodes: NotebookBlockNode[]
): NotebookBlockNode[] {
    if (replacementNodes.length <= 1) {
        return replacementNodes
    }

    const cursorNode = currentNodes[cursorIndex]
    if (!cursorNode) {
        return replacementNodes
    }

    const prefixWithCursorNodes = currentNodes.slice(0, cursorIndex + 1)
    if (prefixWithCursorNodes.length && nodesStartWithNotebookContext(replacementNodes, prefixWithCursorNodes)) {
        return replacementNodes.slice(prefixWithCursorNodes.length)
    }

    const prefixNodes = currentNodes.slice(0, cursorIndex)
    const prefixMatch = getNotebookContextPrefixMatch(replacementNodes, prefixNodes)
    if (!cursorNode || !prefixNodes.length || !prefixMatch) {
        return replacementNodes
    }

    const strippedTailNodes = stripNotebookAIResponseEchoFromTail(
        replacementNodes.slice(prefixNodes.length),
        prefixNodes,
        cursorNode
    )
    const tailNodes = replacementNodes.slice(prefixNodes.length)
    const nextNodes =
        prefixMatch === 'stale' || !nodesHaveSameFingerprints(strippedTailNodes, tailNodes)
            ? strippedTailNodes
            : replacementNodes
    return nextNodes
}

function stripNotebookAIResponseEchoFromTail(
    tailNodes: NotebookBlockNode[],
    prefixNodes: NotebookBlockNode[],
    cursorNode: NotebookBlockNode
): NotebookBlockNode[] {
    let nextNodes = tailNodes
    if (prefixNodes.length && nodesStartWithNotebookContext(nextNodes, prefixNodes)) {
        nextNodes = nextNodes.slice(prefixNodes.length)
    }

    if (nodesStartWith(nextNodes, [cursorNode])) {
        nextNodes = nextNodes.slice(1)
    }

    if (nodesEndWith(nextNodes, [cursorNode])) {
        nextNodes = nextNodes.slice(0, -1)
    }

    return nextNodes
}

function nodesStartWith(nodes: NotebookBlockNode[], prefixNodes: NotebookBlockNode[]): boolean {
    if (nodes.length < prefixNodes.length) {
        return false
    }

    return prefixNodes.every((node, index) => getNodeFingerprint(node) === getNodeFingerprint(nodes[index]))
}

function nodesStartWithNotebookContext(nodes: NotebookBlockNode[], contextNodes: NotebookBlockNode[]): boolean {
    return getNotebookContextPrefixMatch(nodes, contextNodes) !== null
}

function getNotebookContextPrefixMatch(
    nodes: NotebookBlockNode[],
    contextNodes: NotebookBlockNode[]
): 'exact' | 'stale' | null {
    if (nodesStartWith(nodes, contextNodes)) {
        return 'exact'
    }
    if (nodes.length < contextNodes.length) {
        return null
    }

    let hasExactContextBeforeStaleNode = false
    let hasStaleContextNode = false
    const matches = contextNodes.every((contextNode, index) => {
        const candidateNode = nodes[index]
        if (getNodeFingerprint(candidateNode) === getNodeFingerprint(contextNode)) {
            hasExactContextBeforeStaleNode = true
            return true
        }
        if (!hasExactContextBeforeStaleNode) {
            return false
        }
        const isStaleContextNode = isStaleNotebookContextNode(candidateNode, contextNode)
        hasStaleContextNode ||= isStaleContextNode
        return isStaleContextNode
    })

    return matches && hasStaleContextNode ? 'stale' : null
}

function isStaleNotebookContextNode(candidateNode: NotebookBlockNode, currentNode: NotebookBlockNode): boolean {
    if (getNodeSignature(candidateNode) !== getNodeSignature(currentNode) || candidateNode.type === 'component') {
        return false
    }

    const candidateText = normalizeNotebookContextText(getNodeText(candidateNode))
    const currentText = normalizeNotebookContextText(getNodeText(currentNode))
    return !!candidateText.trim() && candidateText.trim().length >= 4 && currentText.startsWith(candidateText)
}

function normalizeNotebookContextText(text: string): string {
    return text.replace(/\u00a0/g, ' ')
}

function nodesEndWith(nodes: NotebookBlockNode[], suffixNodes: NotebookBlockNode[]): boolean {
    if (nodes.length < suffixNodes.length) {
        return false
    }

    const offset = nodes.length - suffixNodes.length
    return suffixNodes.every((node, index) => getNodeFingerprint(node) === getNodeFingerprint(nodes[offset + index]))
}

function nodesHaveSameFingerprints(leftNodes: NotebookBlockNode[], rightNodes: NotebookBlockNode[]): boolean {
    return (
        leftNodes.length === rightNodes.length &&
        leftNodes.every((node, index) => getNodeFingerprint(node) === getNodeFingerprint(rightNodes[index]))
    )
}

function getNotebookAIResponseReplaceRange(
    responseNodeIndex: number,
    replacedNodeCount: number
): { insertionIndex: number; deleteCount: number } {
    const deleteEndExclusive = responseNodeIndex + 1
    const requestedDeleteCount = Math.max(1, Math.floor(replacedNodeCount))
    const insertionIndex = Math.max(0, deleteEndExclusive - requestedDeleteCount)

    return { insertionIndex, deleteCount: deleteEndExclusive - insertionIndex }
}

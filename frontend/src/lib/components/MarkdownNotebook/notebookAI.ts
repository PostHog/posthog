import { parseMarkdownNotebook, serializeMarkdownNotebook } from './markdown'
import type { NotebookBlockNode } from './types'
import { getNodeFingerprint, getNodeSignature, getNodeText } from './utils'

export const NOTEBOOK_AI_WRITING_PLACEHOLDER = 'Thinking...'

export type NotebookAIResponseMarkdownResult = {
    markdown: string
    responseNodeIndex: number
}

export type NotebookAIStreamResponseMarkdownResult = NotebookAIResponseMarkdownResult & {
    responseNodeCount: number
}

export type NotebookAIResponseRange = {
    responseNodeIndex: number
    responseNodeCount: number
}

export function replaceNotebookAIResponseMarkdown(
    markdown: string,
    responseNodeIndex: number,
    replacementMarkdown: string,
    replacedNodeCount: number = 1
): NotebookAIResponseMarkdownResult {
    return applyNotebookAIResponseMarkdown(markdown, responseNodeIndex, replacementMarkdown, replacedNodeCount)
}

export function streamNotebookAIResponseMarkdown(
    markdown: string,
    responseNodeIndex: number,
    replacementMarkdown: string,
    replacedNodeCount: number = 1
): NotebookAIStreamResponseMarkdownResult {
    return applyNotebookAIStreamResponseMarkdown(markdown, responseNodeIndex, replacementMarkdown, replacedNodeCount)
}

export function rebaseNotebookAIResponseRange(
    previousMarkdown: string,
    nextMarkdown: string,
    responseNodeIndex: number,
    responseNodeCount: number
): NotebookAIResponseRange {
    const previousDocument = parseMarkdownNotebook(previousMarkdown)
    const nextDocument = parseMarkdownNotebook(nextMarkdown)
    if (!nextDocument.nodes.length) {
        return { responseNodeIndex: 0, responseNodeCount: 1 }
    }

    const previousRange = getNotebookAIResponseReplaceRange(responseNodeIndex, responseNodeCount)
    const previousStartIndex = Math.min(previousRange.insertionIndex, previousDocument.nodes.length)
    const previousEndIndex = Math.min(
        previousDocument.nodes.length,
        previousRange.insertionIndex + previousRange.deleteCount
    )
    const nextStartIndex = getRebasedNotebookAIResponseStartIndex(
        previousDocument.nodes,
        nextDocument.nodes,
        previousStartIndex
    )
    const nextEndIndex = getRebasedNotebookAIResponseEndIndex(
        previousDocument.nodes,
        nextDocument.nodes,
        previousEndIndex,
        nextStartIndex
    )

    if (nextEndIndex <= nextStartIndex) {
        const fallbackIndex = Math.max(0, Math.min(nextStartIndex, nextDocument.nodes.length - 1))
        return { responseNodeIndex: fallbackIndex, responseNodeCount: 1 }
    }

    return {
        responseNodeIndex: nextEndIndex - 1,
        responseNodeCount: nextEndIndex - nextStartIndex,
    }
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

    const parsedReplacementNodes = withDefaultAIComponentProps(parseMarkdownNotebook(trimmedInsertedMarkdown).nodes)
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

function applyNotebookAIStreamResponseMarkdown(
    markdown: string,
    responseNodeIndex: number,
    insertedMarkdown: string,
    replacedNodeCount: number = 1
): NotebookAIStreamResponseMarkdownResult {
    const trimmedInsertedMarkdown = normalizeNotebookAIInsertedMarkdown(insertedMarkdown).trim()
    if (!trimmedInsertedMarkdown) {
        return { markdown, responseNodeIndex, responseNodeCount: Math.max(1, replacedNodeCount) }
    }

    const document = parseMarkdownNotebook(markdown)
    if (responseNodeIndex < 0 || !document.nodes.length) {
        return { markdown, responseNodeIndex, responseNodeCount: Math.max(1, replacedNodeCount) }
    }

    const parsedReplacementNodes = withDefaultAIComponentProps(parseMarkdownNotebook(trimmedInsertedMarkdown).nodes)
    if (!parsedReplacementNodes.length) {
        return { markdown, responseNodeIndex, responseNodeCount: Math.max(1, replacedNodeCount) }
    }

    const currentResponseNodeIndex = Math.min(responseNodeIndex, document.nodes.length - 1)
    const replacementNodes = stripEchoedNotebookContextBeforeAIResponse(
        document.nodes,
        currentResponseNodeIndex,
        parsedReplacementNodes
    )
    if (!replacementNodes.length) {
        return { markdown, responseNodeIndex, responseNodeCount: Math.max(1, replacedNodeCount) }
    }

    const targetRange = getNotebookAIResponseCurrentReplaceRange(
        document.nodes.length,
        responseNodeIndex,
        replacedNodeCount
    )
    const { insertionIndex, deleteCount } = targetRange
    const currentResponseNodes = document.nodes.slice(insertionIndex, insertionIndex + deleteCount)
    if (!currentResponseNodes.length) {
        return { markdown, responseNodeIndex, responseNodeCount: Math.max(1, replacedNodeCount) }
    }

    const preservedNodes = currentResponseNodes.slice(0, -1)
    const activeNode = currentResponseNodes[currentResponseNodes.length - 1]
    const nextReplacementSearchIndex = getNextReplacementSearchIndexForPreservedNodes(preservedNodes, replacementNodes)
    const activeReplacementIndex = getMatchingReplacementNodeIndex(
        activeNode,
        replacementNodes,
        nextReplacementSearchIndex
    )
    const replacementTailStartIndex = activeReplacementIndex ?? nextReplacementSearchIndex
    const replacementTailNodes = replacementNodes.slice(replacementTailStartIndex)
    if (!replacementTailNodes.length) {
        return { markdown, responseNodeIndex, responseNodeCount: Math.max(1, deleteCount) }
    }

    const nextNodes = [
        ...document.nodes.slice(0, insertionIndex),
        ...preservedNodes,
        ...replacementTailNodes,
        ...document.nodes.slice(insertionIndex + deleteCount),
    ]
    const responseNodeCount = preservedNodes.length + replacementTailNodes.length
    const nextResponseNodeIndex = insertionIndex + responseNodeCount - 1

    return {
        markdown: serializeMarkdownNotebook({
            ...document,
            nodes: nextNodes,
        }),
        responseNodeIndex: nextResponseNodeIndex,
        responseNodeCount,
    }
}

function getRebasedNotebookAIResponseStartIndex(
    previousNodes: NotebookBlockNode[],
    nextNodes: NotebookBlockNode[],
    previousStartIndex: number
): number {
    for (let previousIndex = previousStartIndex - 1; previousIndex >= 0; previousIndex--) {
        const nextIndex = getMatchingNodeFingerprintIndex(previousNodes[previousIndex], nextNodes, 0)
        if (nextIndex !== null) {
            return nextIndex + 1
        }
    }

    return Math.min(previousStartIndex, nextNodes.length)
}

function getRebasedNotebookAIResponseEndIndex(
    previousNodes: NotebookBlockNode[],
    nextNodes: NotebookBlockNode[],
    previousEndIndex: number,
    nextStartIndex: number
): number {
    for (let previousIndex = previousEndIndex; previousIndex < previousNodes.length; previousIndex++) {
        const nextIndex = getMatchingNodeFingerprintIndex(previousNodes[previousIndex], nextNodes, nextStartIndex)
        if (nextIndex !== null) {
            return nextIndex
        }
    }

    return nextNodes.length
}

function getMatchingNodeFingerprintIndex(
    node: NotebookBlockNode,
    candidateNodes: NotebookBlockNode[],
    startIndex: number
): number | null {
    const nodeFingerprint = getNodeFingerprint(node)
    for (let index = Math.max(0, startIndex); index < candidateNodes.length; index++) {
        if (getNodeFingerprint(candidateNodes[index]) === nodeFingerprint) {
            return index
        }
    }

    return null
}

function getNextReplacementSearchIndexForPreservedNodes(
    currentNodes: NotebookBlockNode[],
    replacementNodes: NotebookBlockNode[]
): number {
    let replacementSearchIndex = 0
    for (const currentNode of currentNodes) {
        const matchingIndex = getMatchingReplacementNodeIndex(currentNode, replacementNodes, replacementSearchIndex)
        replacementSearchIndex =
            matchingIndex !== null
                ? matchingIndex + 1
                : Math.min(replacementSearchIndex + 1, Math.max(0, replacementNodes.length - 1))
    }

    return replacementSearchIndex
}

function getMatchingReplacementNodeIndex(
    currentNode: NotebookBlockNode,
    replacementNodes: NotebookBlockNode[],
    startIndex: number
): number | null {
    for (let index = Math.max(0, startIndex); index < replacementNodes.length; index++) {
        if (nodesLikelyRepresentSameAIResponseBlock(currentNode, replacementNodes[index])) {
            return index
        }
    }

    return null
}

function nodesLikelyRepresentSameAIResponseBlock(
    currentNode: NotebookBlockNode,
    replacementNode: NotebookBlockNode
): boolean {
    if (getNodeFingerprint(currentNode) === getNodeFingerprint(replacementNode)) {
        return true
    }
    if (getNodeSignature(currentNode) !== getNodeSignature(replacementNode) || currentNode.type === 'component') {
        return false
    }

    const currentText = normalizeNotebookContextText(getNodeText(currentNode)).trim()
    const replacementText = normalizeNotebookContextText(getNodeText(replacementNode)).trim()
    const commonPrefixLength = getCommonPrefixLength(currentText, replacementText)
    return (
        currentText.length >= 4 &&
        replacementText.length >= 4 &&
        (currentText.startsWith(replacementText) ||
            replacementText.startsWith(currentText) ||
            (commonPrefixLength >= 8 && commonPrefixLength >= Math.min(currentText.length, replacementText.length) / 2))
    )
}

function getCommonPrefixLength(leftText: string, rightText: string): number {
    const maxLength = Math.min(leftText.length, rightText.length)
    for (let index = 0; index < maxLength; index++) {
        if (leftText[index] !== rightText[index]) {
            return index
        }
    }

    return maxLength
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

function withDefaultAIComponentProps(nodes: NotebookBlockNode[]): NotebookBlockNode[] {
    return nodes.map((node) => {
        if (node.type === 'component' && node.tagName === 'Query' && typeof node.props.hideFilters !== 'boolean') {
            return {
                ...node,
                props: {
                    ...node.props,
                    hideFilters: true,
                },
            }
        }

        return node
    })
}

function getSavedInsightQueryMarkdown(shortId: string): string {
    return `<Query hideFilters query={{"kind":"SavedInsightNode","shortId":"${shortId}"}} />`
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

function getNotebookAIResponseCurrentReplaceRange(
    nodeCount: number,
    responseNodeIndex: number,
    replacedNodeCount: number
): { insertionIndex: number; deleteCount: number } {
    const requestedRange = getNotebookAIResponseReplaceRange(responseNodeIndex, replacedNodeCount)
    const deleteEndExclusive = Math.min(nodeCount, responseNodeIndex + 1)
    const insertionIndex = Math.min(requestedRange.insertionIndex, deleteEndExclusive)

    return { insertionIndex, deleteCount: deleteEndExclusive - insertionIndex }
}

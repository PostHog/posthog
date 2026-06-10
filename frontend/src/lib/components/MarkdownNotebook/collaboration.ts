import { parseMarkdownNotebook, serializeMarkdownNotebook, serializeNode } from './markdown'
import { reconcileNotebookDocuments } from './reconcile'
import { NotebookBlockNode, NotebookCollaborationConflict, NotebookDocument } from './types'
import { cloneNotebookNode, getNodeFingerprint, getNodeSignature } from './utils'

export type NotebookMarkdownMergeInput = {
    baseMarkdown: string
    localMarkdown: string
    remoteMarkdown: string
}

export type NotebookMarkdownMergeResult = {
    mergedMarkdown: string
    document: NotebookDocument
    conflicts: NotebookCollaborationConflict[]
}

export function mergeNotebookMarkdownChanges({
    baseMarkdown,
    localMarkdown,
    remoteMarkdown,
}: NotebookMarkdownMergeInput): NotebookMarkdownMergeResult {
    const baseDocument = parseMarkdownNotebook(baseMarkdown)
    const localDocument = reconcileNotebookDocuments(baseDocument, parseMarkdownNotebook(localMarkdown)).document
    const remoteDocument = reconcileNotebookDocuments(baseDocument, parseMarkdownNotebook(remoteMarkdown)).document

    const baseById = new Map(baseDocument.nodes.map((node) => [node.id, node]))
    const localById = new Map(localDocument.nodes.map((node) => [node.id, node]))
    const remoteById = new Map(remoteDocument.nodes.map((node) => [node.id, node]))
    const remoteIndexById = new Map(remoteDocument.nodes.map((node, index) => [node.id, index]))
    const outputNodes: NotebookBlockNode[] = []
    const outputIds = new Set<string>()
    const conflicts: NotebookCollaborationConflict[] = []

    remoteDocument.nodes.forEach((remoteNode) => {
        const baseNode = baseById.get(remoteNode.id)
        const localNode = localById.get(remoteNode.id)

        if (!baseNode) {
            pushOutputNode(outputNodes, outputIds, remoteNode)
            return
        }

        if (!localNode) {
            if (getNodeFingerprint(baseNode) !== getNodeFingerprint(remoteNode)) {
                conflicts.push({
                    nodeId: remoteNode.id,
                    reason: 'Remote changed a block that was deleted locally',
                    localMarkdown: '',
                    remoteMarkdown: serializeNode(remoteNode),
                })
            }
            return
        }

        const baseFingerprint = getNodeFingerprint(baseNode)
        const localFingerprint = getNodeFingerprint(localNode)
        const remoteFingerprint = getNodeFingerprint(remoteNode)
        const localChanged = localFingerprint !== baseFingerprint
        const remoteChanged = remoteFingerprint !== baseFingerprint

        if (localChanged && remoteChanged && localFingerprint !== remoteFingerprint) {
            const mergedNode = mergeNotebookBlockNodeText(baseNode, localNode, remoteNode)
            if (mergedNode) {
                pushOutputNode(outputNodes, outputIds, mergedNode)
                return
            }

            conflicts.push({
                nodeId: remoteNode.id,
                reason: 'Local and remote edited the same block',
                localMarkdown: serializeNode(localNode),
                remoteMarkdown: serializeNode(remoteNode),
            })
            pushOutputNode(outputNodes, outputIds, localNode)
            return
        }

        pushOutputNode(outputNodes, outputIds, localChanged ? localNode : remoteNode)
    })

    localDocument.nodes.forEach((localNode, localIndex) => {
        if (!baseById.has(localNode.id) && !remoteById.has(localNode.id)) {
            if (
                mergeLocalOnlyNodeWithRemoteOnlyOutput(
                    outputNodes,
                    outputIds,
                    baseById,
                    localById,
                    remoteIndexById,
                    localDocument.nodes,
                    remoteDocument.nodes,
                    localIndex,
                    localNode
                )
            ) {
                return
            }
            insertLocalOnlyNode(outputNodes, outputIds, localDocument.nodes, localIndex, localNode)
        }
    })

    const document: NotebookDocument = {
        type: 'doc',
        nodes: outputNodes,
        errors: [...localDocument.errors, ...remoteDocument.errors],
    }

    return {
        document,
        mergedMarkdown: serializeMarkdownNotebook(document),
        conflicts,
    }
}

function pushOutputNode(nodes: NotebookBlockNode[], outputIds: Set<string>, node: NotebookBlockNode): void {
    if (outputIds.has(node.id)) {
        return
    }

    nodes.push(cloneNotebookNode(node))
    outputIds.add(node.id)
}

function insertLocalOnlyNode(
    nodes: NotebookBlockNode[],
    outputIds: Set<string>,
    localNodes: NotebookBlockNode[],
    localIndex: number,
    node: NotebookBlockNode
): void {
    if (outputIds.has(node.id)) {
        return
    }

    const clonedNode = cloneNotebookNode(node)
    const previousAnchor = localNodes
        .slice(0, localIndex)
        .reverse()
        .find((candidate) => outputIds.has(candidate.id))
    if (previousAnchor) {
        const previousOutputIndex = nodes.findIndex((candidate) => candidate.id === previousAnchor.id)
        if (previousOutputIndex !== -1) {
            nodes.splice(previousOutputIndex + 1, 0, clonedNode)
            outputIds.add(clonedNode.id)
            return
        }
    }

    const nextAnchor = localNodes.slice(localIndex + 1).find((candidate) => outputIds.has(candidate.id))
    if (nextAnchor) {
        const nextOutputIndex = nodes.findIndex((candidate) => candidate.id === nextAnchor.id)
        if (nextOutputIndex !== -1) {
            nodes.splice(nextOutputIndex, 0, clonedNode)
            outputIds.add(clonedNode.id)
            return
        }
    }

    nodes.push(clonedNode)
    outputIds.add(clonedNode.id)
}

type SharedAnchorIds = {
    previousId?: string
    nextId?: string
}

function mergeLocalOnlyNodeWithRemoteOnlyOutput(
    nodes: NotebookBlockNode[],
    outputIds: Set<string>,
    baseById: Map<string, NotebookBlockNode>,
    localById: Map<string, NotebookBlockNode>,
    remoteIndexById: Map<string, number>,
    localNodes: NotebookBlockNode[],
    remoteNodes: NotebookBlockNode[],
    localIndex: number,
    localNode: NotebookBlockNode
): boolean {
    const localAnchors = getSharedAnchorIds(localNodes, localIndex, baseById)

    for (let outputIndex = 0; outputIndex < nodes.length; outputIndex++) {
        const remoteOnlyNode = nodes[outputIndex]
        if (baseById.has(remoteOnlyNode.id) || localById.has(remoteOnlyNode.id)) {
            continue
        }

        const remoteIndex = remoteIndexById.get(remoteOnlyNode.id)
        if (remoteIndex === undefined) {
            continue
        }

        const remoteAnchors = getSharedAnchorIds(remoteNodes, remoteIndex, baseById)
        if (!areSharedAnchorIdsEqual(localAnchors, remoteAnchors)) {
            continue
        }

        const mergedNode = mergeInsertedNotebookBlockNodes(localNode, remoteOnlyNode)
        if (!mergedNode) {
            continue
        }

        if (outputIds.has(mergedNode.id) && mergedNode.id !== remoteOnlyNode.id) {
            return false
        }

        nodes[outputIndex] = mergedNode
        outputIds.delete(remoteOnlyNode.id)
        outputIds.add(mergedNode.id)
        return true
    }

    return false
}

function getSharedAnchorIds(
    nodes: NotebookBlockNode[],
    index: number,
    baseById: Map<string, NotebookBlockNode>
): SharedAnchorIds {
    let previousId: string | undefined
    for (let previousIndex = index - 1; previousIndex >= 0; previousIndex--) {
        const candidate = nodes[previousIndex]
        if (baseById.has(candidate.id)) {
            previousId = candidate.id
            break
        }
    }

    let nextId: string | undefined
    for (let nextIndex = index + 1; nextIndex < nodes.length; nextIndex++) {
        const candidate = nodes[nextIndex]
        if (baseById.has(candidate.id)) {
            nextId = candidate.id
            break
        }
    }

    return { previousId, nextId }
}

function areSharedAnchorIdsEqual(left: SharedAnchorIds, right: SharedAnchorIds): boolean {
    return left.previousId === right.previousId && left.nextId === right.nextId
}

function mergeInsertedNotebookBlockNodes(
    localNode: NotebookBlockNode,
    remoteNode: NotebookBlockNode
): NotebookBlockNode | null {
    if (!isMergeableInsertedTextNode(localNode) || !isMergeableInsertedTextNode(remoteNode)) {
        return null
    }
    if (getNodeSignature(localNode) !== getNodeSignature(remoteNode)) {
        return null
    }

    const localMarkdown = serializeNode(localNode)
    const remoteMarkdown = serializeNode(remoteNode)

    if (localMarkdown === remoteMarkdown || isInsertedNodeMarkdownPrefix(localNode, remoteMarkdown, localMarkdown)) {
        return cloneNotebookNode(localNode)
    }

    if (isInsertedNodeMarkdownPrefix(remoteNode, localMarkdown, remoteMarkdown)) {
        return {
            ...cloneNotebookNode(remoteNode),
            id: localNode.id,
        }
    }

    return null
}

function isMergeableInsertedTextNode(node: NotebookBlockNode): boolean {
    return (
        node.type === 'paragraph' ||
        node.type === 'heading' ||
        node.type === 'blockquote' ||
        node.type === 'list' ||
        node.type === 'code'
    )
}

function isInsertedNodeMarkdownPrefix(node: NotebookBlockNode, shorter: string, longer: string): boolean {
    if (node.type === 'list') {
        return longer === shorter || longer.startsWith(`${shorter}\n`)
    }

    return longer.startsWith(shorter)
}

function mergeNotebookBlockNodeText(
    baseNode: NotebookBlockNode,
    localNode: NotebookBlockNode,
    remoteNode: NotebookBlockNode
): NotebookBlockNode | null {
    const baseMarkdown = serializeNode(baseNode)
    const localMarkdown = serializeNode(localNode)
    const remoteMarkdown = serializeNode(remoteNode)
    const mergeResult = mergeTextChanges(baseMarkdown, localMarkdown, remoteMarkdown)
    if (mergeResult.conflicted) {
        return null
    }

    const mergedDocument = parseMarkdownNotebook(mergeResult.text)
    if (mergedDocument.nodes.length !== 1) {
        return null
    }

    return {
        ...mergedDocument.nodes[0],
        id: localNode.id,
    }
}

type TextChange = {
    start: number
    end: number
    text: string
}

type TextMergeResult = {
    text: string
    conflicted: boolean
}

const MAX_EXACT_TEXT_DIFF_CELLS = 4_000_000

function mergeTextChanges(baseText: string, localText: string, remoteText: string): TextMergeResult {
    if (localText === remoteText) {
        return { text: localText, conflicted: false }
    }
    if (baseText === localText) {
        return { text: remoteText, conflicted: false }
    }
    if (baseText === remoteText) {
        return { text: localText, conflicted: false }
    }

    const localChanges = getTextChanges(baseText, localText)
    const remoteChanges = getTextChanges(baseText, remoteText)
    let localIndex = 0
    let remoteIndex = 0
    let baseCursor = 0
    let mergedText = ''

    while (localIndex < localChanges.length || remoteIndex < remoteChanges.length) {
        const localChange = localChanges[localIndex]
        const remoteChange = remoteChanges[remoteIndex]

        if (!remoteChange || (localChange && isChangeBefore(localChange, remoteChange))) {
            mergedText += baseText.slice(baseCursor, localChange.start)
            mergedText += localChange.text
            baseCursor = localChange.end
            localIndex += 1
            continue
        }

        if (!localChange || isChangeBefore(remoteChange, localChange)) {
            mergedText += baseText.slice(baseCursor, remoteChange.start)
            mergedText += remoteChange.text
            baseCursor = remoteChange.end
            remoteIndex += 1
            continue
        }

        const group = collectOverlappingChangeGroup(localChanges, remoteChanges, localIndex, remoteIndex)
        const baseSegment = baseText.slice(group.start, group.end)
        const localSegment = applyTextChanges(
            baseSegment,
            group.localChanges.map((change) => shiftTextChange(change, -group.start))
        )
        const remoteSegment = applyTextChanges(
            baseSegment,
            group.remoteChanges.map((change) => shiftTextChange(change, -group.start))
        )
        const mergedSegment = mergeOverlappingTextSegments(baseSegment, localSegment, remoteSegment)

        if (mergedSegment === null) {
            return { text: localText, conflicted: true }
        }

        mergedText += baseText.slice(baseCursor, group.start)
        mergedText += mergedSegment
        baseCursor = group.end
        localIndex = group.nextLocalIndex
        remoteIndex = group.nextRemoteIndex
    }

    mergedText += baseText.slice(baseCursor)
    return { text: mergedText, conflicted: false }
}

function getTextChanges(baseText: string, nextText: string): TextChange[] {
    if (baseText === nextText) {
        return []
    }

    if (baseText.length * nextText.length > MAX_EXACT_TEXT_DIFF_CELLS) {
        return getSingleSpanTextChange(baseText, nextText)
    }

    const width = nextText.length + 1
    const lcsLengths = new Uint16Array((baseText.length + 1) * width)

    for (let baseIndex = baseText.length - 1; baseIndex >= 0; baseIndex--) {
        for (let nextIndex = nextText.length - 1; nextIndex >= 0; nextIndex--) {
            const offset = baseIndex * width + nextIndex
            lcsLengths[offset] =
                baseText[baseIndex] === nextText[nextIndex]
                    ? lcsLengths[(baseIndex + 1) * width + nextIndex + 1] + 1
                    : Math.max(lcsLengths[(baseIndex + 1) * width + nextIndex], lcsLengths[offset + 1])
        }
    }

    const changes: TextChange[] = []
    let activeChange: TextChange | null = null
    let baseIndex = 0
    let nextIndex = 0

    const ensureActiveChange = (): TextChange => {
        if (!activeChange) {
            activeChange = { start: baseIndex, end: baseIndex, text: '' }
        }
        return activeChange
    }
    const flushActiveChange = (): void => {
        if (activeChange) {
            changes.push(activeChange)
            activeChange = null
        }
    }

    while (baseIndex < baseText.length || nextIndex < nextText.length) {
        if (baseIndex < baseText.length && nextIndex < nextText.length && baseText[baseIndex] === nextText[nextIndex]) {
            flushActiveChange()
            baseIndex += 1
            nextIndex += 1
            continue
        }

        if (
            nextIndex < nextText.length &&
            (baseIndex === baseText.length ||
                lcsLengths[baseIndex * width + nextIndex + 1] >= lcsLengths[(baseIndex + 1) * width + nextIndex])
        ) {
            ensureActiveChange().text += nextText[nextIndex]
            nextIndex += 1
            continue
        }

        ensureActiveChange().end += 1
        baseIndex += 1
    }

    flushActiveChange()
    return changes
}

function getSingleSpanTextChange(baseText: string, nextText: string): TextChange[] {
    let prefixLength = 0
    while (
        prefixLength < baseText.length &&
        prefixLength < nextText.length &&
        baseText[prefixLength] === nextText[prefixLength]
    ) {
        prefixLength += 1
    }

    let suffixLength = 0
    while (
        suffixLength < baseText.length - prefixLength &&
        suffixLength < nextText.length - prefixLength &&
        baseText[baseText.length - suffixLength - 1] === nextText[nextText.length - suffixLength - 1]
    ) {
        suffixLength += 1
    }

    return [
        {
            start: prefixLength,
            end: baseText.length - suffixLength,
            text: nextText.slice(prefixLength, nextText.length - suffixLength),
        },
    ]
}

function isChangeBefore(left: TextChange, right: TextChange): boolean {
    if (left.end < right.start) {
        return true
    }
    if (left.end === right.start && !isSamePositionInsertion(left, right)) {
        return true
    }
    return false
}

function isSamePositionInsertion(left: TextChange, right: TextChange): boolean {
    return left.start === left.end && right.start === right.end && left.start === right.start
}

function collectOverlappingChangeGroup(
    localChanges: TextChange[],
    remoteChanges: TextChange[],
    localIndex: number,
    remoteIndex: number
): {
    start: number
    end: number
    localChanges: TextChange[]
    remoteChanges: TextChange[]
    nextLocalIndex: number
    nextRemoteIndex: number
} {
    let start = Math.min(localChanges[localIndex].start, remoteChanges[remoteIndex].start)
    let end = Math.max(localChanges[localIndex].end, remoteChanges[remoteIndex].end)
    const groupedLocalChanges: TextChange[] = []
    const groupedRemoteChanges: TextChange[] = []
    let nextLocalIndex = localIndex
    let nextRemoteIndex = remoteIndex
    let didGrow = true

    while (didGrow) {
        didGrow = false

        while (
            nextLocalIndex < localChanges.length &&
            doesChangeOverlapRange(localChanges[nextLocalIndex], start, end)
        ) {
            const change = localChanges[nextLocalIndex]
            groupedLocalChanges.push(change)
            start = Math.min(start, change.start)
            end = Math.max(end, change.end)
            nextLocalIndex += 1
            didGrow = true
        }

        while (
            nextRemoteIndex < remoteChanges.length &&
            doesChangeOverlapRange(remoteChanges[nextRemoteIndex], start, end)
        ) {
            const change = remoteChanges[nextRemoteIndex]
            groupedRemoteChanges.push(change)
            start = Math.min(start, change.start)
            end = Math.max(end, change.end)
            nextRemoteIndex += 1
            didGrow = true
        }
    }

    return {
        start,
        end,
        localChanges: groupedLocalChanges,
        remoteChanges: groupedRemoteChanges,
        nextLocalIndex,
        nextRemoteIndex,
    }
}

function doesChangeOverlapRange(change: TextChange, start: number, end: number): boolean {
    if (change.start === change.end && start === end) {
        return change.start === start
    }
    if (change.start === change.end) {
        return change.start >= start && change.start <= end
    }
    return change.start < end && change.end > start
}

function shiftTextChange(change: TextChange, offset: number): TextChange {
    return {
        ...change,
        start: change.start + offset,
        end: change.end + offset,
    }
}

function applyTextChanges(baseText: string, changes: TextChange[]): string {
    let nextText = ''
    let cursor = 0
    changes.forEach((change) => {
        nextText += baseText.slice(cursor, change.start)
        nextText += change.text
        cursor = change.end
    })
    return nextText + baseText.slice(cursor)
}

function mergeOverlappingTextSegments(baseSegment: string, localSegment: string, remoteSegment: string): string | null {
    if (localSegment === remoteSegment) {
        return localSegment
    }
    if (localSegment === baseSegment) {
        return remoteSegment
    }
    if (remoteSegment === baseSegment) {
        return localSegment
    }
    if (localSegment.includes(remoteSegment)) {
        return localSegment
    }
    if (remoteSegment.includes(localSegment)) {
        return remoteSegment
    }
    if (!baseSegment) {
        return `${remoteSegment}${localSegment}`
    }
    return null
}

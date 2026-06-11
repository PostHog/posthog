import { parseMarkdownNotebook, serializeMarkdownNotebook, serializeNode } from './markdown'
import { reconcileNotebookDocuments } from './reconcile'
import { applyTextChanges, getTextChanges, transformTextChanges, tryApplyTextChanges } from './textChanges'
import { NotebookBlockNode, NotebookCollaborationConflict, NotebookDocument } from './types'
import { cloneNotebookNode, getNodeFingerprint, getNodeSignature } from './utils'

export type { TextChange } from './textChanges'
export { tryApplyTextChanges } from './textChanges'

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

    // The deletion still wins (re-adding would resurrect deleted blocks on every merge),
    // but the user must hear about their edit being discarded.
    baseDocument.nodes.forEach((baseNode) => {
        if (remoteById.has(baseNode.id)) {
            return
        }
        const localNode = localById.get(baseNode.id)
        if (localNode && getNodeFingerprint(localNode) !== getNodeFingerprint(baseNode)) {
            conflicts.push({
                nodeId: baseNode.id,
                reason: 'Remote deleted a block that was edited locally',
                localMarkdown: serializeNode(localNode),
                remoteMarkdown: '',
            })
        }
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

    const reconciledMergedDocument = reconcileNotebookDocuments(
        { type: 'doc', nodes: [localNode], errors: [] },
        mergedDocument
    ).document
    const mergedNode = reconciledMergedDocument.nodes[0]
    if (!mergedNode) {
        return null
    }

    return {
        ...mergedNode,
        id: localNode.id,
    }
}

const CRC32_TABLE = ((): Uint32Array => {
    const table = new Uint32Array(256)
    for (let i = 0; i < 256; i++) {
        let value = i
        for (let bit = 0; bit < 8; bit++) {
            value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
        }
        table[i] = value >>> 0
    }
    return table
})()

/** CRC-32 of the string's UTF-16-LE bytes. Mirrors `markdown_crc` in collab.py (zlib.crc32). */
export function markdownCrc(text: string): number {
    let crc = 0xffffffff
    for (let i = 0; i < text.length; i++) {
        const unit = text.charCodeAt(i)
        crc = (crc >>> 8) ^ CRC32_TABLE[(crc ^ (unit & 0xff)) & 0xff]
        crc = (crc >>> 8) ^ CRC32_TABLE[(crc ^ ((unit >>> 8) & 0xff)) & 0xff]
    }
    return (crc ^ 0xffffffff) >>> 0
}

type TextMergeResult = {
    text: string
    conflicted: boolean
}

/**
 * Three-way merge of concurrent edits to one block's markdown, ProseMirror-rebase style:
 * the remote changes are already committed, so local changes are transformed to apply on
 * top of them. Insertions always survive and deletions union, so neither side's typing
 * is ever discarded — at worst both replacements of the same words end up side by side
 * (remote first) and the next save round-trips the result to everyone.
 */
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
    const rebasedLocalChanges = transformTextChanges(localChanges, remoteChanges, 'against-first')
    if (rebasedLocalChanges === null) {
        return { text: localText, conflicted: true }
    }
    const mergedText = tryApplyTextChanges(applyTextChanges(baseText, remoteChanges), rebasedLocalChanges)
    if (mergedText === null) {
        return { text: localText, conflicted: true }
    }

    return { text: mergedText, conflicted: false }
}

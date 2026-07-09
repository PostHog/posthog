import { parseMarkdownNotebook, serializeMarkdownNotebook, serializeNode } from './markdown'
import { getStableComponentKey, reconcileNotebookDocuments } from './reconcile'
import { applyTextChanges, getTextChanges, transformTextChanges, tryApplyTextChanges } from './textChanges'
import {
    NotebookBlockNode,
    NotebookCollaborationConflict,
    NotebookComponentBlockNode,
    NotebookDocument,
    NotebookPropValue,
} from './types'
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
            const mergedComponentNode = mergeNotebookComponentNodes(baseNode, localNode, remoteNode)
            if (mergedComponentNode) {
                pushOutputNode(outputNodes, outputIds, mergedComponentNode)
                return
            }

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
    // The same component inserted on both sides (typically a block racing its own save
    // echo) must collapse to one node, with the local side's prop values winning.
    if (localNode.type === 'component' && remoteNode.type === 'component') {
        if (localNode.tagName !== remoteNode.tagName) {
            return null
        }
        const localKey = getStableComponentKey(localNode)
        if (
            (localKey !== null && localKey === getStableComponentKey(remoteNode)) ||
            getNodeFingerprint(localNode) === getNodeFingerprint(remoteNode)
        ) {
            return {
                ...cloneNotebookNode(localNode),
                props: { ...remoteNode.props, ...localNode.props },
            }
        }
        return null
    }

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

    // Nearly identical versions of one new block are the same block racing its own save
    // (a typo fixed mid-word before the save response landed): keep the local, newer
    // lineage. The threshold is deliberately tight — genuinely different content written
    // by two people at the same spot must stay separate.
    const changes = getTextChanges(remoteMarkdown, localMarkdown)
    const changedUnits = changes.reduce(
        (total, change) => total + Math.max(change.end - change.start, change.text.length),
        0
    )
    if (changedUnits * 5 <= Math.max(localMarkdown.length, remoteMarkdown.length)) {
        return cloneNotebookNode(localNode)
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

/**
 * Per-prop three-way merge for two edits of the same component node, instead of treating
 * the whole tag as one atomic value. Props changed by only one side merge cleanly; string
 * props changed by both sides merge at the text level (so concurrent typing into a prompt
 * question, or a streaming AI answer racing a save echo, composes instead of conflicting).
 * Returns null when any prop genuinely conflicts — the caller falls back to its conflict
 * handling.
 */
function mergeNotebookComponentNodes(
    baseNode: NotebookBlockNode,
    localNode: NotebookBlockNode,
    remoteNode: NotebookBlockNode
): NotebookBlockNode | null {
    if (
        baseNode.type !== 'component' ||
        localNode.type !== 'component' ||
        remoteNode.type !== 'component' ||
        baseNode.tagName !== localNode.tagName ||
        localNode.tagName !== remoteNode.tagName
    ) {
        return null
    }

    const propKeys = new Set([
        ...Object.keys(baseNode.props),
        ...Object.keys(localNode.props),
        ...Object.keys(remoteNode.props),
    ])
    const mergedProps: NotebookComponentBlockNode['props'] = {}

    for (const key of propKeys) {
        const baseValue = baseNode.props[key]
        const localValue = localNode.props[key]
        const remoteValue = remoteNode.props[key]
        const localChanged = !arePropValuesEqual(localValue, baseValue)
        const remoteChanged = !arePropValuesEqual(remoteValue, baseValue)

        let mergedValue: NotebookComponentBlockNode['props'][string] | undefined
        const idArrayMerge = !localChanged
            ? null
            : mergeIdKeyedArrayPropValues(baseValue ?? [], localValue, remoteValue)
        if (!localChanged) {
            mergedValue = remoteValue
        } else if (!remoteChanged || arePropValuesEqual(localValue, remoteValue)) {
            mergedValue = localValue
        } else if (idArrayMerge) {
            mergedValue = idArrayMerge
        } else if (typeof baseValue === 'string' && typeof localValue === 'string' && typeof remoteValue === 'string') {
            const textMerge = mergeTextChanges(baseValue, localValue, remoteValue)
            if (textMerge.conflicted) {
                return null
            }
            mergedValue = textMerge.text
        } else {
            return null
        }

        if (mergedValue !== undefined) {
            mergedProps[key] = mergedValue
        }
    }

    return {
        ...cloneNotebookNode(localNode),
        props: mergedProps,
        // The merged props no longer match either side's source tag
        raw: undefined,
        errors: undefined,
    }
}

type IdKeyedEntry = { [key: string]: NotebookPropValue } & { id: string }

/**
 * Three-way merge for array props whose entries are objects keyed by a unique string `id`
 * (component-level lists being the motivating case). Entries added on either side survive,
 * entries deleted on one side stay deleted, and an entry edited on one side takes that side's
 * version. Returns null when the shape doesn't qualify — the caller falls back to its other
 * strategies.
 */
function mergeIdKeyedArrayPropValues(
    baseValue: NotebookPropValue | undefined,
    localValue: NotebookPropValue | undefined,
    remoteValue: NotebookPropValue | undefined
): NotebookPropValue[] | null {
    const base = asIdKeyedArray(baseValue)
    const local = asIdKeyedArray(localValue)
    const remote = asIdKeyedArray(remoteValue)
    if (!base || !local || !remote) {
        return null
    }

    const baseById = new Map(base.map((entry) => [entry.id, entry]))
    const localById = new Map(local.map((entry) => [entry.id, entry]))
    const merged: IdKeyedEntry[] = []
    const mergedIds = new Set<string>()
    const push = (entry: IdKeyedEntry): void => {
        if (!mergedIds.has(entry.id)) {
            merged.push(entry)
            mergedIds.add(entry.id)
        }
    }

    for (const localEntry of local) {
        const baseEntry = baseById.get(localEntry.id)
        const remoteEntry = remote.find((entry) => entry.id === localEntry.id)

        if (baseEntry && !remoteEntry) {
            // Deleted remotely; a concurrent deletion must not resurrect on every merge.
            continue
        }
        if (remoteEntry && baseEntry && arePropValuesEqual(localEntry, baseEntry)) {
            push(remoteEntry)
            continue
        }
        push(localEntry)
    }

    // Entries the remote side added (or that local deleted but remote edited) are inserted
    // after their closest surviving remote predecessor, keeping both sides' ordering intact.
    remote.forEach((remoteEntry, remoteIndex) => {
        if (mergedIds.has(remoteEntry.id)) {
            return
        }
        const baseEntry = baseById.get(remoteEntry.id)
        if (baseEntry && !localById.has(remoteEntry.id) && arePropValuesEqual(remoteEntry, baseEntry)) {
            // Deleted locally and untouched remotely: the deletion wins.
            return
        }

        let insertIndex = merged.length
        for (let previousIndex = remoteIndex - 1; previousIndex >= 0; previousIndex--) {
            const anchorPosition = merged.findIndex((entry) => entry.id === remote[previousIndex].id)
            if (anchorPosition !== -1) {
                insertIndex = anchorPosition + 1
                break
            }
        }
        merged.splice(insertIndex, 0, remoteEntry)
        mergedIds.add(remoteEntry.id)
    })

    return merged
}

function asIdKeyedArray(value: NotebookPropValue | undefined): IdKeyedEntry[] | null {
    if (!Array.isArray(value)) {
        return null
    }

    const ids = new Set<string>()
    for (const entry of value) {
        if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
            return null
        }
        const id = entry.id
        if (typeof id !== 'string' || !id || ids.has(id)) {
            return null
        }
        ids.add(id)
    }
    return value as IdKeyedEntry[]
}

function arePropValuesEqual(
    left: NotebookComponentBlockNode['props'][string] | undefined,
    right: NotebookComponentBlockNode['props'][string] | undefined
): boolean {
    if (left === undefined || right === undefined) {
        return left === right
    }
    return JSON.stringify(left) === JSON.stringify(right)
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

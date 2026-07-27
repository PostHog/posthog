/**
 * Operation layer over NotebookDocument, inspired by ProseMirror steps and React's vdom
 * diffing: editing code keeps producing whole documents, and operations are derived after
 * the fact by diffing two documents that share node ids. Operations are invertible
 * (apply returns the inverse) and transformable (rebase over concurrent operations),
 * which is what per-user undo and remote-merge survival are built on. The markdown
 * string stays the source of truth — operations are ephemeral, in-memory currency.
 */
import { isTextBlockNode } from './documentModel'
import { parseMarkdownNotebook, serializeNode } from './markdown'
import { reconcileNotebookDocuments } from './reconcile'
import { TextChange, getTextChanges, invertTextChanges, transformTextChanges, tryApplyTextChanges } from './textChanges'
import { NotebookBlockNode, NotebookDocument } from './types'
import { cloneNotebookNode, getNodeFingerprint } from './utils'

export type NotebookTextOperation = {
    type: 'text'
    nodeId: string
    /** Span replacements over the node's serialized markdown. */
    changes: TextChange[]
}

export type NotebookInsertBlockOperation = {
    type: 'insert_block'
    /** Insert after this node; null inserts at the start of the document. */
    afterId: string | null
    node: NotebookBlockNode
}

export type NotebookDeleteBlockOperation = {
    type: 'delete_block'
    nodeId: string
}

export type NotebookReplaceBlockOperation = {
    type: 'replace_block'
    nodeId: string
    node: NotebookBlockNode
}

export type NotebookMoveBlockOperation = {
    type: 'move_block'
    nodeId: string
    /** Move after this node; null moves to the start of the document. */
    afterId: string | null
}

export type NotebookOperation =
    | NotebookTextOperation
    | NotebookInsertBlockOperation
    | NotebookDeleteBlockOperation
    | NotebookReplaceBlockOperation
    | NotebookMoveBlockOperation

export type NotebookOperationApplyResult = {
    document: NotebookDocument
    /** Operations that revert the applied ones, ready to apply to the result document. */
    inverted: NotebookOperation[]
}

/** Block types whose edits are expressed as text changes over their serialized markdown. */
function isTextDiffableNode(node: NotebookBlockNode): boolean {
    return isTextBlockNode(node) || node.type === 'list' || node.type === 'code' || node.type === 'table'
}

/**
 * Derive the operations transforming `fromDocument` into `toDocument`. Nodes are matched
 * by id, so both documents must come from the same editing session (or a reconcile pass).
 */
export function diffNotebookDocuments(
    fromDocument: NotebookDocument,
    toDocument: NotebookDocument
): NotebookOperation[] {
    const operations: NotebookOperation[] = []
    const fromById = new Map(fromDocument.nodes.map((node) => [node.id, node]))
    const toById = new Map(toDocument.nodes.map((node) => [node.id, node]))

    for (const node of fromDocument.nodes) {
        if (!toById.has(node.id)) {
            operations.push({ type: 'delete_block', nodeId: node.id })
        }
    }

    // Surviving nodes that fall outside the longest increasing subsequence of original
    // positions are the minimal set of moves; anchored moves in target order are stable.
    const survivingNodes = toDocument.nodes.filter((node) => fromById.has(node.id))
    const fromIndexById = new Map(fromDocument.nodes.map((node, index) => [node.id, index]))
    const stableIds = getStableNodeIds(survivingNodes.map((node) => fromIndexById.get(node.id) ?? 0))
    survivingNodes.forEach((node, index) => {
        if (stableIds.has(index)) {
            return
        }
        operations.push({
            type: 'move_block',
            nodeId: node.id,
            afterId: index === 0 ? null : survivingNodes[index - 1].id,
        })
    })

    toDocument.nodes.forEach((node, index) => {
        if (fromById.has(node.id)) {
            return
        }
        operations.push({
            type: 'insert_block',
            afterId: index === 0 ? null : toDocument.nodes[index - 1].id,
            node: cloneNotebookNode(node),
        })
    })

    for (const node of toDocument.nodes) {
        const fromNode = fromById.get(node.id)
        if (!fromNode || getNodeFingerprint(fromNode) === getNodeFingerprint(node)) {
            continue
        }

        if (isTextDiffableNode(fromNode) && isTextDiffableNode(node)) {
            const fromMarkdown = serializeNode(fromNode)
            const toMarkdown = serializeNode(node)
            if (fromMarkdown !== toMarkdown) {
                operations.push({ type: 'text', nodeId: node.id, changes: getTextChanges(fromMarkdown, toMarkdown) })
                continue
            }
        }

        operations.push({ type: 'replace_block', nodeId: node.id, node: cloneNotebookNode(node) })
    }

    return operations
}

/** Indexes (into the sequence) of the longest strictly increasing subsequence. */
function getStableNodeIds(sequence: number[]): Set<number> {
    const tailIndexes: number[] = []
    const predecessors = new Array<number>(sequence.length).fill(-1)

    sequence.forEach((value, index) => {
        let low = 0
        let high = tailIndexes.length
        while (low < high) {
            const middle = (low + high) >> 1
            if (sequence[tailIndexes[middle]] < value) {
                low = middle + 1
            } else {
                high = middle
            }
        }
        predecessors[index] = low > 0 ? tailIndexes[low - 1] : -1
        tailIndexes[low] = index
    })

    const stable = new Set<number>()
    let cursor = tailIndexes.length ? tailIndexes[tailIndexes.length - 1] : -1
    while (cursor !== -1) {
        stable.add(cursor)
        cursor = predecessors[cursor]
    }
    return stable
}

/**
 * Apply operations to a document, returning the result and the inverse operations.
 * Returns null when any operation no longer fits the document (stale anchors, spans
 * that don't apply, markdown that no longer parses to a single block) — callers treat
 * that as "this history entry is stale" rather than guessing.
 */
export function applyNotebookOperations(
    document: NotebookDocument,
    operations: NotebookOperation[]
): NotebookOperationApplyResult | null {
    const nodes = [...document.nodes]
    const inverted: NotebookOperation[] = []

    for (const operation of operations) {
        if (operation.type === 'insert_block') {
            if (nodes.some((node) => node.id === operation.node.id)) {
                return null
            }
            const index = getAnchoredIndex(nodes, operation.afterId)
            if (index === null) {
                return null
            }
            nodes.splice(index, 0, cloneNotebookNode(operation.node))
            inverted.push({ type: 'delete_block', nodeId: operation.node.id })
            continue
        }

        if (operation.type === 'delete_block') {
            const index = nodes.findIndex((node) => node.id === operation.nodeId)
            if (index === -1) {
                return null
            }
            const [removed] = nodes.splice(index, 1)
            inverted.push({
                type: 'insert_block',
                afterId: index === 0 ? null : nodes[index - 1].id,
                node: removed,
            })
            continue
        }

        if (operation.type === 'replace_block') {
            const index = nodes.findIndex((node) => node.id === operation.nodeId)
            if (index === -1) {
                return null
            }
            const previous = nodes[index]
            nodes[index] = { ...cloneNotebookNode(operation.node), id: operation.nodeId }
            inverted.push({ type: 'replace_block', nodeId: operation.nodeId, node: previous })
            continue
        }

        if (operation.type === 'move_block') {
            const index = nodes.findIndex((node) => node.id === operation.nodeId)
            if (index === -1) {
                return null
            }
            const previousAfterId = index === 0 ? null : nodes[index - 1].id
            const [moved] = nodes.splice(index, 1)
            const targetIndex = getAnchoredIndex(nodes, operation.afterId)
            if (targetIndex === null) {
                return null
            }
            nodes.splice(targetIndex, 0, moved)
            inverted.push({ type: 'move_block', nodeId: operation.nodeId, afterId: previousAfterId })
            continue
        }

        const index = nodes.findIndex((node) => node.id === operation.nodeId)
        if (index === -1) {
            return null
        }
        const baseNode = nodes[index]
        const baseMarkdown = serializeNode(baseNode)
        const nextMarkdown = tryApplyTextChanges(baseMarkdown, operation.changes)
        if (nextMarkdown === null) {
            return null
        }
        const nextNode = parseNodeMarkdownPreservingIdentity(baseNode, nextMarkdown)
        if (!nextNode) {
            return null
        }
        nodes[index] = nextNode
        inverted.push({
            type: 'text',
            nodeId: operation.nodeId,
            changes: invertTextChanges(baseMarkdown, operation.changes),
        })
        continue
    }

    return {
        document: { ...document, nodes },
        inverted: inverted.reverse(),
    }
}

function getAnchoredIndex(nodes: NotebookBlockNode[], afterId: string | null): number | null {
    if (afterId === null) {
        return 0
    }
    const anchorIndex = nodes.findIndex((node) => node.id === afterId)
    return anchorIndex === -1 ? null : anchorIndex + 1
}

function parseNodeMarkdownPreservingIdentity(
    previousNode: NotebookBlockNode,
    markdown: string
): NotebookBlockNode | null {
    const parsed = parseMarkdownNotebook(markdown)
    if (parsed.nodes.length === 0) {
        return { id: previousNode.id, type: 'paragraph', children: [] }
    }
    if (parsed.nodes.length > 1) {
        return null
    }

    // Reconcile against the previous node so list item ids survive the re-parse.
    const reconciled = reconcileNotebookDocuments({ type: 'doc', nodes: [previousNode], errors: [] }, parsed).document
    const node = reconciled.nodes[0]
    return node ? { ...node, id: previousNode.id } : null
}

type NotebookOperationPair = {
    /** `a` rebased to apply after `b`; null when it became a no-op. */
    a: NotebookOperation | null
    /** `b` rebased to apply after `a`; null when it became a no-op. */
    b: NotebookOperation | null
}

/**
 * Transform two concurrent operations (both rooted at the same document state) past each
 * other. Returns null on a genuine conflict that has no coherent resolution — callers
 * drop the affected history entries rather than apply garbage.
 */
function transformNotebookOperationPair(a: NotebookOperation, b: NotebookOperation): NotebookOperationPair | null {
    const aNodeId = a.type === 'insert_block' ? a.node.id : a.nodeId
    const bNodeId = b.type === 'insert_block' ? b.node.id : b.nodeId

    if (a.type === 'insert_block' || b.type === 'insert_block') {
        if (aNodeId === bNodeId) {
            return null
        }
        if (a.type === 'insert_block' && b.type === 'delete_block' && a.afterId === b.nodeId) {
            return null
        }
        if (b.type === 'insert_block' && a.type === 'delete_block' && b.afterId === a.nodeId) {
            return null
        }
        return { a, b }
    }

    if (aNodeId !== bNodeId) {
        if (a.type === 'move_block' && b.type === 'delete_block' && a.afterId === b.nodeId) {
            return null
        }
        if (b.type === 'move_block' && a.type === 'delete_block' && b.afterId === a.nodeId) {
            return null
        }
        return { a, b }
    }

    if (a.type === 'text' && b.type === 'text') {
        const aChanges = transformTextChanges(a.changes, b.changes, 'against-first')
        const bChanges = transformTextChanges(b.changes, a.changes, 'changes-first')
        if (aChanges === null || bChanges === null) {
            return null
        }
        return {
            a: { ...a, changes: aChanges },
            b: { ...b, changes: bChanges },
        }
    }

    if (a.type === 'delete_block') {
        // After a deletes the node, b has nothing to act on; a survives any change b made.
        return { a: b.type === 'delete_block' ? null : a, b: null }
    }
    if (b.type === 'delete_block') {
        return { a: null, b }
    }

    if (a.type === 'replace_block') {
        // A wholesale replace overrides text edits and other replaces on the same node.
        return { a, b: b.type === 'move_block' ? b : null }
    }
    if (b.type === 'replace_block') {
        return { a: a.type === 'move_block' ? a : null, b }
    }

    if (a.type === 'move_block' && b.type === 'move_block') {
        return null
    }

    // move vs text on the same node: independent concerns.
    return { a, b }
}

export type NotebookOperationListsPair = {
    a: NotebookOperation[]
    b: NotebookOperation[]
}

/**
 * Transform two concurrent operation lists (both rooted at the same document state) past
 * each other: `a` becomes applicable after `b`, and vice versa. Null means conflict.
 */
export function transformNotebookOperationLists(
    a: NotebookOperation[],
    b: NotebookOperation[]
): NotebookOperationListsPair | null {
    let bCurrent = b
    const aTransformed: NotebookOperation[] = []

    for (const aOperation of a) {
        let aCurrent: NotebookOperation | null = aOperation
        const bNext: NotebookOperation[] = []
        for (const bOperation of bCurrent) {
            if (!aCurrent) {
                bNext.push(bOperation)
                continue
            }
            const pair = transformNotebookOperationPair(aCurrent, bOperation)
            if (!pair) {
                return null
            }
            aCurrent = pair.a
            if (pair.b) {
                bNext.push(pair.b)
            }
        }
        if (aCurrent) {
            aTransformed.push(aCurrent)
        }
        bCurrent = bNext
    }

    return { a: aTransformed, b: bCurrent }
}

/**
 * Rebase a history stack over operations that just changed the document (a remote merge
 * or an external value update). `entries[length - 1]` is the entry that applies to the
 * current document; deeper entries apply after the ones above them. Entries that
 * genuinely conflict with the incoming operations are dropped along with everything
 * older — never the whole stack unless everything conflicts.
 */
export function rebaseNotebookOperationStack<T extends { ops: NotebookOperation[] }>(
    entries: T[],
    operations: NotebookOperation[]
): T[] {
    const rebased: T[] = []
    let against = operations

    for (let index = entries.length - 1; index >= 0; index--) {
        const pair = transformNotebookOperationLists(entries[index].ops, against)
        if (!pair) {
            break
        }
        against = pair.b
        if (pair.a.length) {
            rebased.unshift({ ...entries[index], ops: pair.a })
        }
    }

    return rebased
}

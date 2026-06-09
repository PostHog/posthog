import { NotebookBlockNode, NotebookDocument, NotebookReconcileChange } from './types'
import {
    cloneNotebookNode,
    ensureUniqueNodeIds,
    getNodeFingerprint,
    getNodeSignature,
    getNodeText,
    textSimilarity,
} from './utils'

type PreviousNodeEntry = {
    node: NotebookBlockNode
    index: number
    matched: boolean
}

export type NotebookReconcileResult = {
    document: NotebookDocument
    changes: NotebookReconcileChange[]
}

export function reconcileNotebookDocuments(
    previousDocument: NotebookDocument,
    nextDocument: NotebookDocument
): NotebookReconcileResult {
    const previousEntries = previousDocument.nodes.map<PreviousNodeEntry>((node, index) => ({
        node,
        index,
        matched: false,
    }))
    const nextNodes = nextDocument.nodes.map(cloneNotebookNode)

    preserveSameIndexIds(previousEntries, nextNodes)
    preserveExactFingerprintIds(previousEntries, nextNodes)
    preserveStableComponentIds(previousEntries, nextNodes)
    preserveSimilarNodeIds(previousEntries, nextNodes)
    const uniqueNextNodes = ensureUniqueNodeIds(nextNodes)

    const document: NotebookDocument = {
        ...nextDocument,
        nodes: uniqueNextNodes,
    }

    return {
        document,
        changes: getReconcileChanges(previousDocument.nodes, uniqueNextNodes),
    }
}

function preserveSameIndexIds(previousEntries: PreviousNodeEntry[], nextNodes: NotebookBlockNode[]): void {
    nextNodes.forEach((nextNode, index) => {
        const previousEntry = previousEntries[index]
        if (!previousEntry || previousEntry.matched) {
            return
        }

        if (getNodeFingerprint(previousEntry.node) !== getNodeFingerprint(nextNode)) {
            return
        }

        nextNode.id = previousEntry.node.id
        previousEntry.matched = true
    })
}

function preserveExactFingerprintIds(previousEntries: PreviousNodeEntry[], nextNodes: NotebookBlockNode[]): void {
    const entriesByFingerprint = new Map<string, PreviousNodeEntry[]>()
    previousEntries.forEach((entry) => {
        if (entry.matched) {
            return
        }
        const fingerprint = getNodeFingerprint(entry.node)
        entriesByFingerprint.set(fingerprint, [...(entriesByFingerprint.get(fingerprint) ?? []), entry])
    })

    nextNodes.forEach((nextNode) => {
        if (previousEntries.some((entry) => entry.node.id === nextNode.id && entry.matched)) {
            return
        }

        const fingerprint = getNodeFingerprint(nextNode)
        const entries = entriesByFingerprint.get(fingerprint)
        const entry = entries?.find((candidate) => !candidate.matched)
        if (!entry) {
            return
        }

        nextNode.id = entry.node.id
        entry.matched = true
    })
}

function preserveStableComponentIds(previousEntries: PreviousNodeEntry[], nextNodes: NotebookBlockNode[]): void {
    const entriesByComponentKey = new Map<string, PreviousNodeEntry[]>()
    previousEntries.forEach((entry) => {
        if (entry.matched) {
            return
        }

        const componentKey = getStableComponentKey(entry.node)
        if (!componentKey) {
            return
        }

        entriesByComponentKey.set(componentKey, [...(entriesByComponentKey.get(componentKey) ?? []), entry])
    })

    nextNodes.forEach((nextNode) => {
        if (previousEntries.some((entry) => entry.node.id === nextNode.id && entry.matched)) {
            return
        }

        const componentKey = getStableComponentKey(nextNode)
        const entries = componentKey ? entriesByComponentKey.get(componentKey) : null
        const entry = entries?.find((candidate) => !candidate.matched)
        if (!entry) {
            return
        }

        nextNode.id = entry.node.id
        entry.matched = true
    })
}

function getStableComponentKey(node: NotebookBlockNode): string | null {
    if (node.type !== 'component') {
        return null
    }

    const id = node.props.id
    if (typeof id !== 'string' || !id.trim()) {
        return null
    }

    return `${node.tagName}:${id}`
}

function preserveSimilarNodeIds(previousEntries: PreviousNodeEntry[], nextNodes: NotebookBlockNode[]): void {
    nextNodes.forEach((nextNode) => {
        if (previousEntries.some((entry) => entry.node.id === nextNode.id && entry.matched)) {
            return
        }

        const signature = getNodeSignature(nextNode)
        const nextText = getNodeText(nextNode)
        const entry = previousEntries
            .filter((candidate) => !candidate.matched && getNodeSignature(candidate.node) === signature)
            .map((candidate) => ({
                entry: candidate,
                score: textSimilarity(getNodeText(candidate.node), nextText),
            }))
            .sort((left, right) => right.score - left.score)[0]

        if (!entry || entry.score < 0.4) {
            return
        }

        nextNode.id = entry.entry.node.id
        entry.entry.matched = true
    })
}

function getReconcileChanges(
    previousNodes: NotebookBlockNode[],
    nextNodes: NotebookBlockNode[]
): NotebookReconcileChange[] {
    const changes: NotebookReconcileChange[] = []
    const previousById = new Map(previousNodes.map((node, index) => [node.id, { node, index }]))
    const nextById = new Map(nextNodes.map((node, index) => [node.id, { node, index }]))

    previousNodes.forEach((node, previousIndex) => {
        if (!nextById.has(node.id)) {
            changes.push({ type: 'deleted', nodeId: node.id, previousIndex })
        }
    })

    nextNodes.forEach((node, index) => {
        const previous = previousById.get(node.id)
        if (!previous) {
            changes.push({ type: 'inserted', nodeId: node.id, index })
            return
        }

        if (previous.index !== index) {
            changes.push({ type: 'moved', nodeId: node.id, previousIndex: previous.index, index })
        }

        if (getNodeFingerprint(previous.node) !== getNodeFingerprint(node)) {
            changes.push({ type: 'updated', nodeId: node.id, index })
        }
    })

    return changes
}

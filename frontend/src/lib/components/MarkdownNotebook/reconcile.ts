import {
    NotebookBlockNode,
    NotebookDocument,
    NotebookListBlockNode,
    NotebookListItem,
    NotebookReconcileChange,
} from './types'
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
    preserveListItemIds(previousDocument.nodes, nextNodes)
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

export function getStableComponentKey(node: NotebookBlockNode): string | null {
    if (node.type !== 'component') {
        return null
    }

    const id = node.props.id
    if (typeof id !== 'string' || !id.trim()) {
        return null
    }

    return `${node.tagName}:${id}`
}

function preserveListItemIds(previousNodes: NotebookBlockNode[], nextNodes: NotebookBlockNode[]): void {
    const previousById = new Map(previousNodes.map((node) => [node.id, node]))

    nextNodes.forEach((nextNode) => {
        if (nextNode.type !== 'list') {
            return
        }

        const previousNode = previousById.get(nextNode.id)
        if (previousNode?.type !== 'list') {
            return
        }

        preserveListNodeItemIds(previousNode, nextNode)
    })
}

function preserveListNodeItemIds(previousNode: NotebookListBlockNode, nextNode: NotebookListBlockNode): void {
    const previousMatchedIndexes = new Set<number>()
    const nextMatchedIndexes = new Set<number>()
    const previousExactIndexesByFingerprint = new Map<string, number[]>()

    previousNode.items.forEach((item, index) => {
        if (!item.id) {
            return
        }

        const fingerprint = getListItemIdentityFingerprint(item)
        previousExactIndexesByFingerprint.set(fingerprint, [
            ...(previousExactIndexesByFingerprint.get(fingerprint) ?? []),
            index,
        ])
    })

    nextNode.items.forEach((item, index) => {
        const fingerprint = getListItemIdentityFingerprint(item)
        const previousIndexes = previousExactIndexesByFingerprint.get(fingerprint)
        const previousIndex = previousIndexes?.find((candidateIndex) => !previousMatchedIndexes.has(candidateIndex))
        if (previousIndex === undefined) {
            return
        }

        const previousItem = previousNode.items[previousIndex]
        if (!previousItem?.id) {
            return
        }

        item.id = previousItem.id
        previousMatchedIndexes.add(previousIndex)
        nextMatchedIndexes.add(index)
    })

    if (previousNode.items.length !== nextNode.items.length) {
        return
    }

    nextNode.items.forEach((item, index) => {
        if (nextMatchedIndexes.has(index) || previousMatchedIndexes.has(index)) {
            return
        }

        const previousItem = previousNode.items[index]
        if (!previousItem?.id) {
            return
        }

        item.id = previousItem.id
        previousMatchedIndexes.add(index)
        nextMatchedIndexes.add(index)
    })
}

function getListItemIdentityFingerprint(item: NotebookListItem): string {
    return JSON.stringify({
        children: item.children,
        depth: item.depth,
        ordered: item.ordered,
        start: item.start,
    })
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

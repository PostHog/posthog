import { parseMarkdownNotebook, serializeMarkdownNotebook, serializeNode } from './markdown'
import { reconcileNotebookDocuments } from './reconcile'
import { NotebookBlockNode, NotebookCollaborationConflict, NotebookDocument } from './types'
import { cloneNotebookNode, getNodeFingerprint } from './utils'

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

    localDocument.nodes.forEach((localNode) => {
        if (!baseById.has(localNode.id) && !remoteById.has(localNode.id)) {
            pushOutputNode(outputNodes, outputIds, localNode)
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

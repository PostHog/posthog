import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NotebookNodeType } from '../types'

export type PythonNodeSummary = {
    nodeId: string
    code: string
    globalsUsed: string[]
    pythonIndex: number
    title: string
}

export type VariableUsage = {
    nodeId: string
    pythonIndex: number
    title: string
}

export const collectPythonNodes = (content?: JSONContent | null): PythonNodeSummary[] => {
    if (!content || typeof content !== 'object') {
        return []
    }

    const nodes: PythonNodeSummary[] = []

    const walk = (node: any): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        if (node.type === NotebookNodeType.Python) {
            const attrs = node.attrs ?? {}
            nodes.push({
                nodeId: attrs.nodeId ?? '',
                code: typeof attrs.code === 'string' ? attrs.code : '',
                globalsUsed: Array.isArray(attrs.globalsUsed) ? attrs.globalsUsed : [],
                pythonIndex: nodes.length + 1,
                title: typeof attrs.title === 'string' ? attrs.title : '',
            })
        }
        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)
    return nodes
}

export const collectNodeIndices = (
    content: Record<string, any> | null | undefined,
    predicate: (node: Record<string, any>) => boolean
): Map<string, number> => {
    if (!content || typeof content !== 'object') {
        return new Map()
    }

    const nodeIndices = new Map<string, number>()
    let currentIndex = 0

    const walk = (node: Record<string, any> | null | undefined): void => {
        if (!node || typeof node !== 'object') {
            return
        }

        if (predicate(node)) {
            const nodeId = node.attrs?.nodeId
            if (nodeId) {
                currentIndex += 1
                nodeIndices.set(nodeId, currentIndex)
            }
        }

        if (Array.isArray(node.content)) {
            node.content.forEach(walk)
        }
    }

    walk(content)
    return nodeIndices
}

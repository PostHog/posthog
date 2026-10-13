import { getMarkdownNotebookVisualGroups } from './documentModel'
import type { NotebookBlockNode } from './types'

/**
 * A notebook seen as Jupyter cells. A run of text blocks that share a card is one markdown cell,
 * the way a Jupyter markdown cell holds several paragraphs; a code cell and any other block (an
 * insight, a recording, a divider) stand alone. A cell is named by its first node's id.
 */
export type NotebookJupyterCell = {
    id: string
    kind: 'code' | 'markdown' | 'block'
    nodeIds: string[]
    startIndex: number
    endIndex: number
}

export function getNotebookJupyterCells(
    nodes: NotebookBlockNode[],
    isCodeCell: (node: NotebookBlockNode) => boolean
): NotebookJupyterCell[] {
    return getMarkdownNotebookVisualGroups(nodes).map((group) => {
        if (group.type === 'text') {
            const first = group.items[0]
            const last = group.items[group.items.length - 1]
            return {
                id: first.node.id,
                kind: 'markdown',
                nodeIds: group.items.map((item) => item.node.id),
                startIndex: first.index,
                endIndex: last.index,
            }
        }
        return {
            id: group.node.id,
            kind: isCodeCell(group.node) ? 'code' : 'block',
            nodeIds: [group.node.id],
            startIndex: group.index,
            endIndex: group.index,
        }
    })
}

export function findNotebookJupyterCellIndex(cells: NotebookJupyterCell[], nodeId: string | null): number {
    if (!nodeId) {
        return -1
    }
    return cells.findIndex((cell) => cell.nodeIds.includes(nodeId))
}

export function getNotebookJupyterCellRange(
    cells: NotebookJupyterCell[],
    anchorCellId: string,
    activeCellId: string
): string[] {
    const anchorIndex = findNotebookJupyterCellIndex(cells, anchorCellId)
    const activeIndex = findNotebookJupyterCellIndex(cells, activeCellId)
    if (anchorIndex === -1 || activeIndex === -1) {
        return activeIndex === -1 ? [] : [cells[activeIndex].id]
    }
    const [from, to] = anchorIndex <= activeIndex ? [anchorIndex, activeIndex] : [activeIndex, anchorIndex]
    return cells.slice(from, to + 1).map((cell) => cell.id)
}

import { InsertMenuSelectionDirection, TableCellPosition } from './editorTypes'
import { NotebookTableBlockNode, NotebookTableCell } from './types'

export function getTableCellRefKey(nodeId: string, position: TableCellPosition): string {
    return `${nodeId}:${position.section}:${String(position.rowIndex)}:${String(position.columnIndex)}`
}

export function getTableColumnCount(node: NotebookTableBlockNode): number {
    return Math.max(1, node.headers.length, node.alignments?.length ?? 0, ...node.rows.map((row) => row.length))
}

export function normalizeTableRow(row: NotebookTableCell[], columnCount: number): NotebookTableCell[] {
    return Array.from({ length: columnCount }, (_, index) => row[index] ?? { children: [] })
}

export function makeEmptyTableRow(columnCount: number): NotebookTableCell[] {
    return Array.from({ length: columnCount }, () => ({ children: [] }))
}

export function getTableCellPositions(node: NotebookTableBlockNode): TableCellPosition[] {
    const columnCount = getTableColumnCount(node)
    return [
        ...Array.from({ length: columnCount }, (_, columnIndex) => ({
            section: 'header' as const,
            rowIndex: 0,
            columnIndex,
        })),
        ...node.rows.flatMap((_, rowIndex) =>
            Array.from({ length: columnCount }, (_, columnIndex) => ({
                section: 'body' as const,
                rowIndex,
                columnIndex,
            }))
        ),
    ]
}

export function getTableEdgeCellPosition(
    node: NotebookTableBlockNode,
    direction: InsertMenuSelectionDirection
): TableCellPosition | null {
    const positions = getTableCellPositions(node)
    return direction === 'next' ? (positions[0] ?? null) : (positions[positions.length - 1] ?? null)
}

export function getTableCellAtPosition(
    node: NotebookTableBlockNode,
    position: TableCellPosition
): NotebookTableCell | undefined {
    if (position.section === 'header') {
        return node.headers[position.columnIndex]
    }
    return node.rows[position.rowIndex]?.[position.columnIndex]
}

export function tableCellPositionsEqual(left: TableCellPosition, right: TableCellPosition): boolean {
    return left.section === right.section && left.rowIndex === right.rowIndex && left.columnIndex === right.columnIndex
}

export function getTableCellPositionFromElement(element: HTMLElement): TableCellPosition | null {
    const section = element.dataset.markdownNotebookTableSection
    const rowIndex = Number(element.dataset.markdownNotebookTableRowIndex)
    const columnIndex = Number(element.dataset.markdownNotebookTableColumnIndex)
    if ((section !== 'header' && section !== 'body') || !Number.isInteger(rowIndex) || !Number.isInteger(columnIndex)) {
        return null
    }

    return { section, rowIndex, columnIndex }
}

import type { MarkdownNotebookVisualGroup } from './documentModel'
import { makeEmptyParagraph } from './markdown'
import type { NotebookBlockNode, NotebookComponentBlockNode, NotebookComponentProps } from './types'

export const COLUMN_LAYOUT_TAGS = ['Columns', 'Column', 'ColumnEnd', 'ColumnsEnd'] as const

export function isColumnLayoutNode(node: NotebookBlockNode): boolean {
    return node.type === 'component' && COLUMN_LAYOUT_TAGS.some((tag) => tag === node.tagName)
}

export function getColumnWidths(props: NotebookComponentProps, count: number): number[] {
    const widths = Array.isArray(props.widths) ? props.widths : []
    return Array.from({ length: count }, (_, index) => {
        const width = widths[index]
        return typeof width === 'number' && Number.isFinite(width) && width >= 1 && width <= 12 ? width : 1
    })
}

export type NotebookColumnGroup = {
    start: Extract<MarkdownNotebookVisualGroup, { type: 'block' }>
    groups: MarkdownNotebookVisualGroup[]
    end: Extract<MarkdownNotebookVisualGroup, { type: 'block' }>
}

export type NotebookColumnsGroup = {
    type: 'columns'
    key: string
    start: Extract<MarkdownNotebookVisualGroup, { type: 'block' }> & { node: NotebookComponentBlockNode }
    columns: NotebookColumnGroup[]
    end: Extract<MarkdownNotebookVisualGroup, { type: 'block' }>
}

function groupTag(group: MarkdownNotebookVisualGroup | undefined): string | undefined {
    return group?.type === 'block' && group.node.type === 'component' ? group.node.tagName : undefined
}

function readColumns(groups: MarkdownNotebookVisualGroup[], start: number): NotebookColumnsGroup | null {
    const opening = groups[start]
    if (
        opening.type !== 'block' ||
        opening.node.type !== 'component' ||
        opening.node.tagName !== 'Columns' ||
        opening.node.errors?.length
    ) {
        return null
    }
    const columns: NotebookColumnGroup[] = []
    let index = start + 1
    while (groupTag(groups[index]) === 'Column') {
        const columnStart = groups[index++] as NotebookColumnGroup['start']
        const content: MarkdownNotebookVisualGroup[] = []
        while (index < groups.length && !COLUMN_LAYOUT_TAGS.some((tag) => tag === groupTag(groups[index]))) {
            content.push(groups[index++])
        }
        if (groupTag(groups[index]) !== 'ColumnEnd') {
            return null
        }
        columns.push({ start: columnStart, groups: content, end: groups[index++] as NotebookColumnGroup['end'] })
    }
    if (groupTag(groups[index]) !== 'ColumnsEnd' || columns.length < 2 || columns.length > 4) {
        return null
    }
    return {
        type: 'columns',
        key: opening.key,
        start: { ...opening, node: opening.node },
        columns,
        end: groups[index] as NotebookColumnsGroup['end'],
    }
}

export function groupNotebookColumns(
    groups: MarkdownNotebookVisualGroup[]
): (MarkdownNotebookVisualGroup | NotebookColumnsGroup)[] {
    const result: (MarkdownNotebookVisualGroup | NotebookColumnsGroup)[] = []
    for (let index = 0; index < groups.length; index++) {
        const columns = readColumns(groups, index)
        if (columns) {
            result.push(columns)
            index = groups.indexOf(columns.end)
        } else {
            result.push(groups[index])
        }
    }
    return result
}

export function makeColumnNodes(): NotebookBlockNode[] {
    return [
        { id: makeEmptyParagraph('column').id, type: 'component', tagName: 'Column', props: {} },
        makeEmptyParagraph('column-content'),
        { id: makeEmptyParagraph('column-end').id, type: 'component', tagName: 'ColumnEnd', props: {} },
    ]
}

export function makeColumnsNodes(start: NotebookComponentBlockNode): NotebookBlockNode[] {
    return [
        start,
        ...Array.from({ length: 2 }, makeColumnNodes).flat(),
        { id: makeEmptyParagraph('columns-end').id, type: 'component', tagName: 'ColumnsEnd', props: {} },
    ]
}

export function resizeNotebookColumns(
    nodes: NotebookBlockNode[],
    group: NotebookColumnsGroup,
    count: number
): NotebookBlockNode[] {
    if (!Number.isInteger(count) || count < 2 || count > 4) {
        return nodes
    }
    const startIndex = nodes.findIndex((node) => node.id === group.start.node.id)
    const endIndex = nodes.findIndex((node) => node.id === group.end.node.id)
    if (startIndex < 0 || endIndex < startIndex) {
        return nodes
    }
    const content = nodes.slice(startIndex + 1, endIndex)
    if (count < group.columns.length) {
        const removedMarkers = new Set(
            group.columns
                .slice(count - 1)
                .flatMap((column, index, columns) => [
                    ...(index > 0 ? [column.start.node.id] : []),
                    ...(index < columns.length - 1 ? [column.end.node.id] : []),
                ])
        )
        return [
            ...nodes.slice(0, startIndex),
            {
                ...group.start.node,
                props: { ...group.start.node.props, widths: getColumnWidths(group.start.node.props, count) },
            },
            ...content.filter((node) => !removedMarkers.has(node.id)),
            ...nodes.slice(endIndex),
        ]
    }
    return [
        ...nodes.slice(0, startIndex),
        {
            ...group.start.node,
            props: { ...group.start.node.props, widths: getColumnWidths(group.start.node.props, count) },
        },
        ...content,
        ...Array.from({ length: count - group.columns.length }, makeColumnNodes).flat(),
        ...nodes.slice(endIndex),
    ]
}

export function isInsideNotebookColumns(nodes: NotebookBlockNode[], nodeId: string | undefined): boolean {
    let depth = 0
    for (const node of nodes) {
        if (node.id === nodeId) {
            return depth > 0
        }
        if (node.type === 'component' && node.tagName === 'Columns') {
            depth++
        } else if (node.type === 'component' && node.tagName === 'ColumnsEnd') {
            depth = Math.max(0, depth - 1)
        }
    }
    return false
}

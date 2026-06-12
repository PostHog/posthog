import clsx from 'clsx'
import {
    ClipboardEvent as ReactClipboardEvent,
    FormEvent,
    MutableRefObject,
    type CSSProperties,
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from 'react'

import { IconMinus, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { shouldUseMarkdownPaste } from './documentModel'
import { getInlineLinkPasteResult, getSelectionRange } from './domSelection'
import { RestoreSelectionRequest, TableCellPosition, TextSelectionPointerStartEvent } from './editorTypes'
import { splitInlineNodesAt } from './inlineContent'
import { htmlElementToInlineNodes, inlineNodesToHtml, parseMarkdownNotebook } from './markdown'
import { getTableColumnCount, makeEmptyTableRow, normalizeTableRow } from './tableModel'
import { NotebookBlockNode, NotebookInlineNode, NotebookMode, NotebookTableBlockNode, NotebookTableCell } from './types'
import { getInlineText, normalizeInlineNodes } from './utils'

export type TableStructureControlLayout = {
    tableLeft: number
    tableTop: number
    tableWidth: number
    tableHeight: number
    rowInsertTops: number[]
    rowRemoveRects: { top: number; height: number }[]
    columnInsertLefts: number[]
    columnRemoveRects: { left: number; width: number }[]
}

export function areNumberArraysEqual(left: number[], right: number[]): boolean {
    return left.length === right.length && left.every((value, index) => value === right[index])
}

export function areControlRectsEqual(
    left: { top?: number; left?: number; width?: number; height?: number }[],
    right: { top?: number; left?: number; width?: number; height?: number }[]
): boolean {
    return (
        left.length === right.length &&
        left.every((value, index) => {
            const rightValue = right[index]
            return (
                value.top === rightValue.top &&
                value.left === rightValue.left &&
                value.width === rightValue.width &&
                value.height === rightValue.height
            )
        })
    )
}

export function areTableStructureControlLayoutsEqual(
    left: TableStructureControlLayout | null,
    right: TableStructureControlLayout
): boolean {
    return Boolean(
        left &&
        left.tableLeft === right.tableLeft &&
        left.tableTop === right.tableTop &&
        left.tableWidth === right.tableWidth &&
        left.tableHeight === right.tableHeight &&
        areNumberArraysEqual(left.rowInsertTops, right.rowInsertTops) &&
        areControlRectsEqual(left.rowRemoveRects, right.rowRemoveRects) &&
        areNumberArraysEqual(left.columnInsertLefts, right.columnInsertLefts) &&
        areControlRectsEqual(left.columnRemoveRects, right.columnRemoveRects)
    )
}

export function tableControlStyle(variables: Record<string, string>): CSSProperties {
    return variables as CSSProperties
}

export function EditableTableBlock({
    node,
    mode,
    setBlockRef,
    setTableCellRef,
    updateNode,
    handleSelectionChange,
    startTextSelectionPointer,
    restoreSelectionRef,
}: {
    node: NotebookTableBlockNode
    mode: NotebookMode
    setBlockRef: (element: HTMLElement | null) => void
    setTableCellRef: (position: TableCellPosition, element: HTMLElement | null) => void
    updateNode: (nodeId: string, updater: (node: NotebookBlockNode) => NotebookBlockNode | null) => void
    handleSelectionChange: () => void
    startTextSelectionPointer: (event: TextSelectionPointerStartEvent) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    const columnCount = getTableColumnCount(node)
    const headers = normalizeTableRow(node.headers, columnCount)
    const rows = node.rows.map((row) => normalizeTableRow(row, columnCount))
    const tableGridRef = useRef<HTMLDivElement | null>(null)
    const tableRef = useRef<HTMLTableElement | null>(null)
    const [controlLayout, setControlLayout] = useState<TableStructureControlLayout | null>(null)

    const updateTableControlLayout = useCallback((): void => {
        if (mode !== 'edit') {
            return
        }

        const tableGrid = tableGridRef.current
        const table = tableRef.current
        if (!tableGrid || !table) {
            return
        }

        const gridRect = tableGrid.getBoundingClientRect()
        const tableRect = table.getBoundingClientRect()
        const headerRow = table.tHead?.rows[0]
        const bodyRows = Array.from(table.tBodies[0]?.rows ?? [])
        const headerCells = headerRow ? Array.from(headerRow.cells) : []

        const rowInsertTops = headerRow
            ? [
                  headerRow.getBoundingClientRect().bottom - gridRect.top,
                  ...bodyRows.map((row) => row.getBoundingClientRect().bottom - gridRect.top),
              ]
            : []
        const rowRemoveRects = bodyRows.map((row) => {
            const rowRect = row.getBoundingClientRect()
            return {
                top: rowRect.top - gridRect.top,
                height: rowRect.height,
            }
        })
        const columnInsertLefts = headerCells.length
            ? [
                  headerCells[0].getBoundingClientRect().left - gridRect.left,
                  ...headerCells.map((cell) => cell.getBoundingClientRect().right - gridRect.left),
              ]
            : []
        const columnRemoveRects = headerCells.map((cell) => {
            const cellRect = cell.getBoundingClientRect()
            return {
                left: cellRect.left - gridRect.left,
                width: cellRect.width,
            }
        })

        const nextLayout: TableStructureControlLayout = {
            tableLeft: tableRect.left - gridRect.left,
            tableTop: tableRect.top - gridRect.top,
            tableWidth: tableRect.width,
            tableHeight: tableRect.height,
            rowInsertTops,
            rowRemoveRects,
            columnInsertLefts,
            columnRemoveRects,
        }

        setControlLayout((previousLayout) =>
            areTableStructureControlLayoutsEqual(previousLayout, nextLayout) ? previousLayout : nextLayout
        )
    }, [mode])

    useLayoutEffect(() => {
        updateTableControlLayout()
    }, [columnCount, rows.length, updateTableControlLayout])

    useEffect(() => {
        if (mode !== 'edit') {
            return
        }

        const table = tableRef.current
        const ownerWindow = table?.ownerDocument.defaultView
        if (!table || !ownerWindow) {
            return
        }

        updateTableControlLayout()

        if (ownerWindow.ResizeObserver) {
            const resizeObserver = new ownerWindow.ResizeObserver(updateTableControlLayout)
            resizeObserver.observe(table)
            return () => resizeObserver.disconnect()
        }

        ownerWindow.addEventListener('resize', updateTableControlLayout)
        return () => ownerWindow.removeEventListener('resize', updateTableControlLayout)
    }, [mode, updateTableControlLayout])

    const updateTableCell = (position: TableCellPosition, children: NotebookInlineNode[]): void => {
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'table') {
                return currentNode
            }

            if (position.section === 'header') {
                const nextHeaders = normalizeTableRow(currentNode.headers, columnCount)
                nextHeaders[position.columnIndex] = { children }
                return { ...currentNode, headers: nextHeaders }
            }

            const nextRows = currentNode.rows.map((row) => normalizeTableRow(row, columnCount))
            const nextRow = nextRows[position.rowIndex] ?? makeEmptyTableRow(columnCount)
            nextRow[position.columnIndex] = { children }
            nextRows[position.rowIndex] = nextRow
            return { ...currentNode, rows: nextRows }
        })
    }

    const addTableRowAfter = (rowIndex: number, columnIndex: number): void => {
        const insertIndex = Math.max(0, Math.min(rowIndex + 1, rows.length))
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'table') {
                return currentNode
            }

            const nextRows = currentNode.rows.map((row) => normalizeTableRow(row, columnCount))
            nextRows.splice(insertIndex, 0, makeEmptyTableRow(columnCount))
            return { ...currentNode, rows: nextRows }
        })
        restoreSelectionRef.current = {
            nodeId: node.id,
            tableCell: { section: 'body', rowIndex: insertIndex, columnIndex },
            start: 0,
            end: 0,
        }
    }

    const removeTableRow = (rowIndex: number): void => {
        if (!rows.length) {
            return
        }

        const removeIndex = Math.max(0, Math.min(rowIndex, rows.length - 1))
        const nextRowCount = rows.length - 1
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'table') {
                return currentNode
            }

            const nextRows = currentNode.rows
                .map((row) => normalizeTableRow(row, columnCount))
                .filter((_, currentRowIndex) => currentRowIndex !== removeIndex)
            return { ...currentNode, rows: nextRows }
        })
        restoreSelectionRef.current = nextRowCount
            ? {
                  nodeId: node.id,
                  tableCell: {
                      section: 'body',
                      rowIndex: Math.max(0, Math.min(removeIndex, nextRowCount - 1)),
                      columnIndex: 0,
                  },
                  start: 0,
                  end: 0,
              }
            : {
                  nodeId: node.id,
                  tableCell: { section: 'header', rowIndex: 0, columnIndex: 0 },
                  start: 0,
                  end: 0,
              }
    }

    const addTableColumnAfter = (columnIndex: number): void => {
        const insertIndex = Math.max(0, Math.min(columnIndex + 1, columnCount))
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'table') {
                return currentNode
            }

            const nextHeaders = normalizeTableRow(currentNode.headers, columnCount)
            nextHeaders.splice(insertIndex, 0, { children: [] })
            const nextRows = currentNode.rows.map((row) => {
                const nextRow = normalizeTableRow(row, columnCount)
                nextRow.splice(insertIndex, 0, { children: [] })
                return nextRow
            })
            const nextAlignments = currentNode.alignments
                ? Array.from({ length: columnCount }, (_, index) => currentNode.alignments?.[index])
                : undefined
            nextAlignments?.splice(insertIndex, 0, undefined)

            return {
                ...currentNode,
                headers: nextHeaders,
                rows: nextRows,
                alignments: nextAlignments,
            }
        })
        restoreSelectionRef.current = {
            nodeId: node.id,
            tableCell: { section: 'header', rowIndex: 0, columnIndex: insertIndex },
            start: 0,
            end: 0,
        }
    }

    const removeTableColumn = (columnIndex: number): void => {
        if (columnCount <= 1) {
            return
        }

        const removeIndex = Math.max(0, Math.min(columnIndex, columnCount - 1))
        const nextColumnIndex = Math.max(0, Math.min(removeIndex, columnCount - 2))
        updateNode(node.id, (currentNode) => {
            if (currentNode.type !== 'table') {
                return currentNode
            }

            const nextHeaders = normalizeTableRow(currentNode.headers, columnCount).filter(
                (_, currentColumnIndex) => currentColumnIndex !== removeIndex
            )
            const nextRows = currentNode.rows.map((row) =>
                normalizeTableRow(row, columnCount).filter(
                    (_, currentColumnIndex) => currentColumnIndex !== removeIndex
                )
            )
            const nextAlignments = currentNode.alignments
                ? Array.from({ length: columnCount }, (_, index) => currentNode.alignments?.[index]).filter(
                      (_, currentColumnIndex) => currentColumnIndex !== removeIndex
                  )
                : undefined

            return {
                ...currentNode,
                headers: nextHeaders,
                rows: nextRows,
                alignments: nextAlignments,
            }
        })
        restoreSelectionRef.current = {
            nodeId: node.id,
            tableCell: { section: 'header', rowIndex: 0, columnIndex: nextColumnIndex },
            start: 0,
            end: 0,
        }
    }

    const tableLeft = controlLayout?.tableLeft ?? 0
    const tableTop = controlLayout?.tableTop ?? 0
    const tableWidth = controlLayout?.tableWidth ?? 0
    const tableHeight = controlLayout?.tableHeight ?? 0
    const rowInsertControls = [
        {
            key: 'row-start',
            rowIndex: -1,
            top: controlLayout?.rowInsertTops[0] ?? tableTop,
            label: rows.length ? 'Add row before row 1' : 'Add row',
            tooltip: rows.length ? 'Add row above' : 'Add row',
        },
        ...rows.map((_, rowIndex) => ({
            key: `row-after-${rowIndex}`,
            rowIndex,
            top: controlLayout?.rowInsertTops[rowIndex + 1] ?? tableTop,
            label: `Add row after row ${rowIndex + 1}`,
            tooltip: 'Add row below',
        })),
    ]
    const columnInsertControls = [
        {
            key: 'column-start',
            columnIndex: -1,
            left: controlLayout?.columnInsertLefts[0] ?? tableLeft,
            label: 'Add column before column 1',
            tooltip: 'Add column before',
        },
        ...headers.map((_, columnIndex) => ({
            key: `column-after-${columnIndex}`,
            columnIndex,
            left: controlLayout?.columnInsertLefts[columnIndex + 1] ?? tableLeft,
            label: `Add column after column ${columnIndex + 1}`,
            tooltip: 'Add column after',
        })),
    ]

    return (
        <div
            className={clsx(
                'MarkdownNotebook__table-block',
                mode === 'edit' && 'MarkdownNotebook__table-block--editable'
            )}
            ref={setBlockRef}
        >
            <div className="MarkdownNotebook__table-scroll">
                <div className="MarkdownNotebook__table-grid" ref={tableGridRef}>
                    <table ref={tableRef}>
                        <thead>
                            <tr>
                                {headers.map((cell, columnIndex) => (
                                    <th key={columnIndex}>
                                        <EditableTableCellContent
                                            node={node}
                                            cell={cell}
                                            position={{ section: 'header', rowIndex: 0, columnIndex }}
                                            mode={mode}
                                            setTableCellRef={setTableCellRef}
                                            updateTableCell={updateTableCell}
                                            handleSelectionChange={handleSelectionChange}
                                            startTextSelectionPointer={startTextSelectionPointer}
                                            restoreSelectionRef={restoreSelectionRef}
                                        />
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((row, rowIndex) => (
                                <tr key={rowIndex}>
                                    {row.map((cell, columnIndex) => (
                                        <td key={columnIndex}>
                                            <EditableTableCellContent
                                                node={node}
                                                cell={cell}
                                                position={{ section: 'body', rowIndex, columnIndex }}
                                                mode={mode}
                                                setTableCellRef={setTableCellRef}
                                                updateTableCell={updateTableCell}
                                                handleSelectionChange={handleSelectionChange}
                                                startTextSelectionPointer={startTextSelectionPointer}
                                                restoreSelectionRef={restoreSelectionRef}
                                            />
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    {mode === 'edit' ? (
                        <div className="MarkdownNotebook__table-structure-overlay" contentEditable={false}>
                            {rowInsertControls.map((control) => (
                                <div
                                    className="MarkdownNotebook__table-add-zone MarkdownNotebook__table-row-add-zone"
                                    key={control.key}
                                    style={tableControlStyle({
                                        '--table-control-left': `${tableLeft}px`,
                                        '--table-control-top': `${control.top}px`,
                                        '--table-control-width': `${tableWidth}px`,
                                    })}
                                >
                                    <TableStructureControlButton
                                        label={control.label}
                                        tooltip={control.tooltip}
                                        icon={<IconPlus />}
                                        onClick={() => addTableRowAfter(control.rowIndex, 0)}
                                    />
                                </div>
                            ))}
                            {columnInsertControls.map((control) => (
                                <div
                                    className="MarkdownNotebook__table-add-zone MarkdownNotebook__table-column-add-zone"
                                    key={control.key}
                                    style={tableControlStyle({
                                        '--table-control-left': `${control.left}px`,
                                        '--table-control-top': `${tableTop}px`,
                                        '--table-control-height': `${tableHeight}px`,
                                    })}
                                >
                                    <TableStructureControlButton
                                        label={control.label}
                                        tooltip={control.tooltip}
                                        icon={<IconPlus />}
                                        onClick={() => addTableColumnAfter(control.columnIndex)}
                                    />
                                </div>
                            ))}
                            {rows.map((_, rowIndex) => {
                                const rowRect = controlLayout?.rowRemoveRects[rowIndex]
                                return (
                                    <div
                                        className="MarkdownNotebook__table-remove-zone MarkdownNotebook__table-row-remove-zone"
                                        key={`remove-row-${rowIndex}`}
                                        style={tableControlStyle({
                                            '--table-control-left': `${tableLeft}px`,
                                            '--table-control-top': `${rowRect?.top ?? tableTop}px`,
                                            '--table-control-height': `${rowRect?.height ?? 0}px`,
                                        })}
                                    >
                                        <TableStructureControlButton
                                            label={`Remove row ${rowIndex + 1}`}
                                            tooltip="Remove row"
                                            icon={<IconMinus />}
                                            onClick={() => removeTableRow(rowIndex)}
                                        />
                                    </div>
                                )
                            })}
                            {headers.map((_, columnIndex) => {
                                const columnRect = controlLayout?.columnRemoveRects[columnIndex]
                                return (
                                    <div
                                        className="MarkdownNotebook__table-remove-zone MarkdownNotebook__table-column-remove-zone"
                                        key={`remove-column-${columnIndex}`}
                                        style={tableControlStyle({
                                            '--table-control-left': `${columnRect?.left ?? tableLeft}px`,
                                            '--table-control-top': `${tableTop}px`,
                                            '--table-control-width': `${columnRect?.width ?? 0}px`,
                                        })}
                                    >
                                        <TableStructureControlButton
                                            label={`Remove column ${columnIndex + 1}`}
                                            tooltip="Remove column"
                                            icon={<IconMinus />}
                                            disabledReason={
                                                columnCount <= 1 ? 'Tables need at least one column' : undefined
                                            }
                                            onClick={() => removeTableColumn(columnIndex)}
                                        />
                                    </div>
                                )
                            })}
                        </div>
                    ) : null}
                </div>
            </div>
        </div>
    )
}

export function TableStructureControlButton({
    label,
    tooltip,
    icon,
    disabledReason,
    onClick,
}: {
    label: string
    tooltip: string
    icon: JSX.Element
    disabledReason?: string
    onClick: () => void
}): JSX.Element {
    return (
        <LemonButton
            aria-label={label}
            className="MarkdownNotebook__table-structure-control"
            disabledReason={disabledReason}
            icon={icon}
            noPadding
            size="xsmall"
            tooltip={tooltip}
            onClick={onClick}
            onMouseDown={(event) => {
                event.preventDefault()
                event.stopPropagation()
            }}
        />
    )
}

export function EditableTableCellContent({
    node,
    cell,
    position,
    mode,
    setTableCellRef,
    updateTableCell,
    handleSelectionChange,
    startTextSelectionPointer,
    restoreSelectionRef,
}: {
    node: NotebookTableBlockNode
    cell: NotebookTableCell
    position: TableCellPosition
    mode: NotebookMode
    setTableCellRef: (position: TableCellPosition, element: HTMLElement | null) => void
    updateTableCell: (position: TableCellPosition, children: NotebookInlineNode[]) => void
    handleSelectionChange: () => void
    startTextSelectionPointer: (event: TextSelectionPointerStartEvent) => void
    restoreSelectionRef: MutableRefObject<RestoreSelectionRequest | null>
}): JSX.Element {
    const elementRef = useRef<HTMLDivElement | null>(null)
    const skipDomSyncForHtmlRef = useRef<string | null>(null)
    const renderedHtml = useMemo(() => inlineNodesToHtml(cell.children), [cell.children])

    const setElementRef = useCallback(
        (element: HTMLDivElement | null): void => {
            elementRef.current = element
            setTableCellRef(position, element)
        },
        [position, setTableCellRef]
    )

    useLayoutEffect(() => {
        const element = elementRef.current
        if (!element) {
            return
        }

        const shouldSkipOwnInputSync =
            document.activeElement === element && skipDomSyncForHtmlRef.current === renderedHtml
        skipDomSyncForHtmlRef.current = null

        if (shouldSkipOwnInputSync || element.innerHTML === renderedHtml) {
            return
        }

        // While the caret is inside the cell, the DOM is the source of the latest model state:
        // rewriting innerHTML would destroy the caret mid-typing, so only sync when the live DOM
        // does not already represent the same content.
        const selection = window.getSelection()
        if (
            selection?.anchorNode &&
            element.contains(selection.anchorNode) &&
            inlineNodesToHtml(htmlElementToInlineNodes(element)) === renderedHtml
        ) {
            return
        }

        element.innerHTML = renderedHtml
    }, [renderedHtml])

    const updateChildren = (nextChildren: NotebookInlineNode[]): NotebookInlineNode[] => {
        skipDomSyncForHtmlRef.current = inlineNodesToHtml(nextChildren)
        updateTableCell(position, nextChildren)
        return nextChildren
    }

    const handleInput = (event: FormEvent<HTMLDivElement>): void => {
        updateChildren(htmlElementToInlineNodes(event.currentTarget))
    }

    const handlePaste = (event: ReactClipboardEvent<HTMLDivElement>): void => {
        const plainText = event.clipboardData.getData('text/plain')
        const html = event.clipboardData.getData('text/html')
        const linkPasteResult = getInlineLinkPasteResult(event.currentTarget, node.id, cell.children, plainText)
        if (linkPasteResult) {
            event.preventDefault()
            updateChildren(linkPasteResult.children)
            restoreSelectionRef.current = {
                nodeId: node.id,
                tableCell: position,
                start: linkPasteResult.start,
                end: linkPasteResult.end,
            }
            return
        }

        const pastedDocument = plainText ? parseMarkdownNotebook(plainText) : null
        if (
            pastedDocument &&
            pastedDocument.nodes.length === 1 &&
            pastedDocument.nodes[0].type === 'paragraph' &&
            shouldUseMarkdownPaste(plainText, html, pastedDocument)
        ) {
            event.preventDefault()
            const selection = getSelectionRange(event.currentTarget, node.id)
            const currentTextLength = getInlineText(cell.children).length
            const selectionStart = selection ? Math.min(selection.start, selection.end) : currentTextLength
            const selectionEnd = selection ? Math.max(selection.start, selection.end) : currentTextLength
            const [beforeSelection, selectionAndAfter] = splitInlineNodesAt(cell.children, selectionStart)
            const [, afterSelection] = splitInlineNodesAt(selectionAndAfter, selectionEnd - selectionStart)
            const nextChildren = normalizeInlineNodes([
                ...beforeSelection,
                ...pastedDocument.nodes[0].children,
                ...afterSelection,
            ])
            const nextCaretOffset =
                getInlineText(beforeSelection).length + getInlineText(pastedDocument.nodes[0].children).length
            updateChildren(nextChildren)
            restoreSelectionRef.current = {
                nodeId: node.id,
                tableCell: position,
                start: nextCaretOffset,
                end: nextCaretOffset,
            }
            return
        }

        if (!html) {
            return
        }

        event.preventDefault()
        const container = document.createElement('div')
        container.innerHTML = html
        document.execCommand('insertHTML', false, inlineNodesToHtml(htmlElementToInlineNodes(container)))
        updateChildren(htmlElementToInlineNodes(event.currentTarget))
    }

    return (
        <div
            ref={setElementRef}
            className="MarkdownNotebook__table-cell-content"
            data-markdown-notebook-node-id={node.id}
            data-markdown-notebook-table-section={position.section}
            data-markdown-notebook-table-row-index={position.rowIndex}
            data-markdown-notebook-table-column-index={position.columnIndex}
            contentEditable={mode === 'edit'}
            suppressContentEditableWarning
            onInput={handleInput}
            onPaste={handlePaste}
            onMouseDown={startTextSelectionPointer}
            onPointerDown={startTextSelectionPointer}
            onTouchStart={startTextSelectionPointer}
            onMouseUp={handleSelectionChange}
            onKeyUp={handleSelectionChange}
        />
    )
}

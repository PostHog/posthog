import { useValues } from 'kea'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { IconArrowLeft, IconArrowRight, IconDrag, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { richContentEditorLogic } from 'lib/components/RichContentEditor/richContentEditorLogic'
import { Popover } from 'lib/lemon-ui/Popover'

const GRIP_OFFSET = 6
const GRIP_SIZE = 20

type GripMode = 'row' | 'col'

type HoveredCell = {
    rowIndex: number
    colIndex: number
    row: HTMLTableRowElement
    cell: HTMLTableCellElement
    table: HTMLTableElement
}

type MenuAction = {
    label: string
    icon: JSX.Element
    onClick: () => void
    status?: 'danger'
}

function GripHandle({
    mode,
    hoveredCell,
    isMenuOpen,
    actions,
    onCloseMenu,
    onClick,
}: {
    mode: GripMode
    hoveredCell: HoveredCell
    isMenuOpen: boolean
    actions: MenuAction[]
    onCloseMenu: () => void
    onClick: () => void
}): JSX.Element {
    const wrapperRef = useRef<HTMLDivElement>(null)

    useLayoutEffect(() => {
        const wrapper = wrapperRef.current
        if (!wrapper) {
            return
        }
        const tableRect = hoveredCell.table.getBoundingClientRect()
        switch (mode) {
            case 'row': {
                const rowRect = hoveredCell.row.getBoundingClientRect()
                wrapper.style.top = `${rowRect.top}px`
                wrapper.style.left = `${tableRect.left - GRIP_SIZE - GRIP_OFFSET}px`
                wrapper.style.width = `${GRIP_SIZE + GRIP_OFFSET}px`
                wrapper.style.height = `${rowRect.height}px`
                break
            }
            case 'col': {
                const cellRect = hoveredCell.cell.getBoundingClientRect()
                wrapper.style.top = `${tableRect.top - GRIP_SIZE - GRIP_OFFSET}px`
                wrapper.style.left = `${cellRect.left}px`
                wrapper.style.width = `${cellRect.width}px`
                wrapper.style.height = `${GRIP_SIZE + GRIP_OFFSET}px`
                break
            }
        }
    }, [hoveredCell, mode])

    return (
        // Wrapper extends from the icon to the table edge, bridging the hover gap
        <div ref={wrapperRef} className="fixed flex items-center justify-center z-0" data-table-grip>
            <Popover
                visible={isMenuOpen}
                onClickOutside={onCloseMenu}
                placement={mode === 'row' ? 'right-start' : 'bottom-start'}
                className={mode === 'col' ? 'mt-1' : 'ml-1'}
                overlay={
                    <div className="flex flex-col p-1 min-w-40">
                        {actions.map((action, i) => (
                            <div key={action.label}>
                                {i > 0 && action.status === 'danger' && actions[i - 1]?.status !== 'danger' && (
                                    <LemonDivider className="my-1" />
                                )}
                                <LemonButton
                                    onClick={action.onClick}
                                    icon={action.icon}
                                    status={action.status}
                                    size="small"
                                    fullWidth
                                >
                                    {action.label}
                                </LemonButton>
                            </div>
                        ))}
                    </div>
                }
            >
                <LemonButton
                    size="xsmall"
                    noPadding
                    icon={<IconDrag className={`text-tertiary text-lg${mode === 'col' ? ' rotate-90' : ''}`} />}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        onClick()
                    }}
                />
            </Popover>
        </div>
    )
}

export function TableMenu(): JSX.Element | null {
    const { ttEditor } = useValues(richContentEditorLogic)
    const [hoveredCell, setHoveredCell] = useState<HoveredCell | null>(null)
    const [activeMenu, setActiveMenu] = useState<GripMode | null>(null)

    useEffect(() => {
        if (!ttEditor) {
            return
        }

        const handleMouseMove = (e: MouseEvent): void => {
            // When a menu is open, freeze the grip position
            if (activeMenu) {
                return
            }

            const target = e.target as HTMLElement

            // If mouse is over a grip wrapper, keep current state
            if (target.closest('[data-table-grip]')) {
                return
            }

            // Check if mouse is over a table cell
            const cell = target.closest('td, th') as HTMLTableCellElement | null
            const table = cell?.closest('table') as HTMLTableElement | null
            const editorEl = ttEditor.view.dom

            if (!cell || !table || !editorEl.contains(cell) || cell.closest('.NotebookNode')) {
                setHoveredCell(null)
                return
            }

            // Get row/col indices from the DOM structure
            const row = cell.closest('tr')!
            const rows = Array.from(table.querySelectorAll(':scope > thead > tr, :scope > tbody > tr, :scope > tr'))
            const rowIndex = rows.indexOf(row)
            const colIndex = Array.from(row.children).indexOf(cell)
            if (rowIndex < 0 || colIndex < 0) {
                return
            }
            setHoveredCell({ rowIndex, colIndex, row, cell, table })
        }

        document.addEventListener('mousemove', handleMouseMove)
        return () => {
            document.removeEventListener('mousemove', handleMouseMove)
        }
    }, [ttEditor, activeMenu])

    /** Returns a 2D array [row][col] of ProseMirror cell positions for the hovered table */
    const getTableCellPositions = useCallback((): number[][] => {
        if (!ttEditor || !hoveredCell) {
            return []
        }
        const tablePos = ttEditor.view.posAtDOM(hoveredCell.table, 0) - 1
        const tableNode = ttEditor.state.doc.nodeAt(tablePos)
        if (!tableNode || tableNode.type.name !== 'table') {
            return []
        }
        const positions: number[][] = []
        tableNode.forEach((rowNode, rowOffset) => {
            const rowPos = tablePos + 1 + rowOffset
            const rowCells: number[] = []
            rowNode.forEach((_cellNode, cellOffset) => {
                rowCells.push(rowPos + 1 + cellOffset)
            })
            positions.push(rowCells)
        })
        return positions
    }, [ttEditor, hoveredCell])

    const runCommand = useCallback(
        (command: string): void => {
            if (!ttEditor || !hoveredCell) {
                return
            }
            // Focus the hovered cell so the command operates on the right row/col
            const cellPos = getTableCellPositions()[hoveredCell.rowIndex]?.[hoveredCell.colIndex]
            if (cellPos === undefined) {
                return
            }
            ttEditor.commands.focus()
            ttEditor.commands.setTextSelection(cellPos + 1) // +1 to get inside cell content
            ;(ttEditor.chain().focus() as any)[command]().run()
            setActiveMenu(null)
            setHoveredCell(null)
        },
        [ttEditor, hoveredCell, getTableCellPositions]
    )

    const selectCells = useCallback(
        (mode: GripMode): void => {
            if (!ttEditor || !hoveredCell) {
                return
            }
            const positions = getTableCellPositions()
            if (mode === 'row') {
                const row = positions[hoveredCell.rowIndex]
                if (row && row.length >= 1) {
                    ttEditor
                        .chain()
                        .focus()
                        .setCellSelection({ anchorCell: row[0], headCell: row[row.length - 1] })
                        .run()
                }
            } else {
                const col = hoveredCell.colIndex
                if (positions.length >= 1 && positions[0][col] !== undefined) {
                    ttEditor
                        .chain()
                        .focus()
                        .setCellSelection({
                            anchorCell: positions[0][col],
                            headCell: positions[positions.length - 1][col],
                        })
                        .run()
                }
            }
        },
        [ttEditor, hoveredCell, getTableCellPositions]
    )

    if (!ttEditor) {
        return null
    }

    const showRow = hoveredCell && (!activeMenu || activeMenu === 'row')
    const showCol = hoveredCell && (!activeMenu || activeMenu === 'col')

    return (
        <>
            {showRow && (
                <GripHandle
                    mode="row"
                    hoveredCell={hoveredCell}
                    isMenuOpen={activeMenu === 'row'}
                    actions={[
                        {
                            label: 'Insert above',
                            icon: <IconArrowRight className="-rotate-90" />,
                            onClick: () => runCommand('addRowBefore'),
                        },
                        {
                            label: 'Insert below',
                            icon: <IconArrowRight className="rotate-90" />,
                            onClick: () => runCommand('addRowAfter'),
                        },
                        {
                            label: 'Delete row',
                            icon: <IconTrash />,
                            onClick: () => runCommand('deleteRow'),
                            status: 'danger',
                        },
                    ]}
                    onCloseMenu={() => setActiveMenu(null)}
                    onClick={() => {
                        selectCells('row')
                        setActiveMenu((prev) => (prev === 'row' ? null : 'row'))
                    }}
                />
            )}
            {showCol && (
                <GripHandle
                    mode="col"
                    hoveredCell={hoveredCell}
                    isMenuOpen={activeMenu === 'col'}
                    actions={[
                        { label: 'Insert left', icon: <IconArrowLeft />, onClick: () => runCommand('addColumnBefore') },
                        {
                            label: 'Insert right',
                            icon: <IconArrowRight />,
                            onClick: () => runCommand('addColumnAfter'),
                        },
                        {
                            label: 'Delete column',
                            icon: <IconTrash />,
                            onClick: () => runCommand('deleteColumn'),
                            status: 'danger',
                        },
                    ]}
                    onCloseMenu={() => setActiveMenu(null)}
                    onClick={() => {
                        selectCells('col')
                        setActiveMenu((prev) => (prev === 'col' ? null : 'col'))
                    }}
                />
            )}
        </>
    )
}

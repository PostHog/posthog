import { type ColumnDef } from '@tanstack/react-table'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { DataTable } from './data-table'

// Base UI's Checkbox constructs PointerEvents, which jsdom doesn't implement.
if (typeof window.PointerEvent === 'undefined') {
    window.PointerEvent = class extends MouseEvent {} as typeof window.PointerEvent
}

interface TestRow {
    name: string
}

const data: TestRow[] = [{ name: 'Ada' }]

describe('DataTable', () => {
    afterEach(cleanup)

    it.each([
        ['label', <label key="label">Toggle</label>],
        ['contenteditable element', <span key="editable" contentEditable />],
        ['custom control', <span key="control" role="button" />],
        ['consumer opt-out', <span key="opt-out" data-row-click-ignore />],
    ])('does not activate a row from a %s', (_name, control) => {
        const onRowClick = jest.fn()
        const columns: ColumnDef<TestRow>[] = [
            {
                accessorKey: 'name',
                header: 'Name',
                cell: () => control,
            },
        ]
        const { container } = render(<DataTable columns={columns} data={data} onRowClick={onRowClick} />)

        fireEvent.click(container.querySelector('tbody td > *')!)

        expect(onRowClick).not.toHaveBeenCalled()
    })

    it('activates a row from non-interactive content', () => {
        const onRowClick = jest.fn()
        const columns: ColumnDef<TestRow>[] = [{ accessorKey: 'name', header: 'Name' }]
        render(<DataTable columns={columns} data={data} onRowClick={onRowClick} />)

        fireEvent.click(screen.getByText('Ada'))

        expect(onRowClick).toHaveBeenCalledWith(data[0])
    })

    it('shows a selection made from a cell on the row', () => {
        const columns: ColumnDef<TestRow>[] = [
            {
                id: 'select',
                cell: ({ row }) => (
                    <input type="checkbox" checked={row.getIsSelected()} onChange={() => row.toggleSelected()} />
                ),
            },
            { accessorKey: 'name', header: 'Name' },
        ]
        const { container } = render(<DataTable columns={columns} data={data} />)

        fireEvent.click(screen.getByRole('checkbox'))

        expect(container.querySelector('tbody tr')!.getAttribute('data-state')).toBe('selected')
        expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true)
    })

    it.each([
        ['selects', [], ['Ada', 'Grace', 'Linus', 'Margaret']],
        ['clears', ['Ada', 'Grace', 'Linus', 'Margaret', 'Ken'], ['Ken']],
    ])('shift-click %s the selectable rows between two checkboxes', (_name, initial, expected) => {
        const people: TestRow[] = ['Ada', 'Grace', 'Barbara', 'Linus', 'Margaret', 'Ken'].map((name) => ({ name }))
        const onRowSelectionChange = jest.fn()
        const { container } = render(
            <DataTable
                columns={[{ accessorKey: 'name', header: 'Name' }]}
                data={people}
                selectable
                rowSelectionDisabledReason={(row) => (row.name === 'Barbara' ? 'Not selectable' : null)}
                getRowId={(row) => row.name}
                rowSelectionLabel={(row) => `Select ${row.name}`}
                rowSelection={Object.fromEntries(initial.map((name) => [name, true]))}
                onRowSelectionChange={onRowSelectionChange}
            />
        )

        const checkbox = (name: string): Element =>
            container.querySelector(`[role="checkbox"][aria-label="Select ${name}"]`)!
        fireEvent.click(checkbox('Ada'))
        onRowSelectionChange.mockClear()
        fireEvent.click(checkbox('Margaret'), { shiftKey: true })

        const next = onRowSelectionChange.mock.calls[0][0]
        expect(Object.keys(next).sort()).toEqual([...expected].sort())
    })

    it.each([
        ['disables a row when a reason appears', () => null, () => 'Not selectable', true],
        ['enables a row again when the reason callback is removed', () => 'Not selectable', undefined, false],
    ] as const)('%s', (_name, before, after, disabledAfter) => {
        const columns: ColumnDef<TestRow>[] = [{ accessorKey: 'name', header: 'Name' }]
        const people: TestRow[] = [{ name: 'Ada' }]
        const rowSelection = {}
        const { container, rerender } = render(
            <DataTable
                columns={columns}
                data={people}
                selectable
                rowSelectionDisabledReason={before}
                rowSelection={rowSelection}
            />
        )
        const checkbox = (): Element => container.querySelector('tbody [role="checkbox"]')!
        expect(checkbox().hasAttribute('data-disabled')).toBe(!disabledAfter)

        rerender(
            <DataTable
                columns={columns}
                data={people}
                selectable
                rowSelectionDisabledReason={after}
                rowSelection={rowSelection}
            />
        )

        expect(checkbox().hasAttribute('data-disabled')).toBe(disabledAfter)
    })

    it('applies a row class name per row', () => {
        const columns: ColumnDef<TestRow>[] = [{ accessorKey: 'name', header: 'Name' }]
        const { container } = render(
            <DataTable
                columns={columns}
                data={[{ name: 'Ada' }, { name: 'Grace' }]}
                rowClassName={(row) => (row.name === 'Grace' ? 'highlighted-row' : undefined)}
            />
        )
        const rows = container.querySelectorAll('tbody tr')

        expect(rows[0].classList.contains('highlighted-row')).toBe(false)
        expect(rows[1].classList.contains('highlighted-row')).toBe(true)
    })

    it('reports page changes with one-based page numbers', () => {
        const onPageChange = jest.fn()
        const columns: ColumnDef<TestRow>[] = [{ accessorKey: 'name', header: 'Name' }]
        render(
            <DataTable
                columns={columns}
                data={[{ name: 'Ada' }, { name: 'Grace' }]}
                pageSize={1}
                onPageChange={onPageChange}
            />
        )

        fireEvent.click(screen.getByLabelText('Go to page 2'))

        expect(onPageChange).toHaveBeenCalledWith(1, 2)
    })

    describe('resizable columns', () => {
        afterEach(cleanup)

        const columns: ColumnDef<TestRow>[] = [
            { accessorKey: 'name', header: 'Name', minSize: 100, maxSize: 110 },
            { id: 'actions', header: '', enableResizing: false, cell: () => null },
        ]
        const resizer = (): HTMLElement => screen.getByLabelText('Resize Name column')
        const columnWidth = (index: number): string =>
            (screen.getByRole('table').querySelectorAll('col')[index] as HTMLElement).style.width

        it('has no resizer until asked for', () => {
            render(<DataTable columns={columns} data={data} />)

            expect(screen.queryByRole('separator')).toBeNull()
        })

        it('leaves out a column that opts out', () => {
            render(<DataTable columns={columns} data={data} resizableColumns />)

            expect(screen.getAllByRole('separator')).toHaveLength(1)
        })

        it('keeps the content layout until the first resize', () => {
            render(<DataTable columns={columns} data={data} resizableColumns />)
            expect(screen.getByRole('table').getAttribute('data-layout')).toBeNull()

            fireEvent.keyDown(resizer(), { key: 'ArrowRight' })

            expect(screen.getByRole('table').getAttribute('data-layout')).toBe('fixed')
        })

        it.each([
            ['grows', 104, 'ArrowRight', 110],
            ['shrinks', 106, 'ArrowLeft', 100],
            ['stops at the maximum', 110, 'ArrowRight', 110],
            ['stops at the minimum', 100, 'ArrowLeft', 100],
        ])('%s with the arrow keys', (_name, start, key, expected) => {
            const onColumnSizingChange = jest.fn()
            render(
                <DataTable
                    columns={columns}
                    data={data}
                    resizableColumns
                    columnSizing={{ name: start }}
                    onColumnSizingChange={onColumnSizingChange}
                />
            )

            fireEvent.keyDown(resizer(), { key })

            expect(onColumnSizingChange).toHaveBeenCalledWith({ name: expected })
        })

        it('applies restored widths without a resize', () => {
            render(<DataTable columns={columns} data={data} resizableColumns columnSizing={{ name: 105 }} />)

            expect(screen.getByRole('table').getAttribute('data-layout')).toBe('fixed')
            expect(columnWidth(0)).toBe('105px')
        })

        // pinned: rendering the rows on each move takes far longer than a frame in a large table.
        describe('while dragging', () => {
            beforeEach(() => {
                jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 200 } as DOMRect)
                jest.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
                    callback(0)
                    return 0
                })
            })

            afterEach(() => {
                jest.restoreAllMocks()
            })

            const drag = (grip: HTMLElement, moves: number[]): void => {
                act(() => {
                    grip.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 0, bubbles: true }))
                })
                for (const clientX of moves) {
                    act(() => {
                        grip.dispatchEvent(new MouseEvent('pointermove', { clientX, bubbles: true }))
                    })
                }
                act(() => {
                    grip.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }))
                })
            }

            it('never renders the rows, and reports the width once at the end', () => {
                const renderCell = jest.fn(() => null)
                const onColumnSizingChange = jest.fn()
                const counted: ColumnDef<TestRow>[] = [
                    { accessorKey: 'name', header: 'Name', cell: renderCell },
                    { id: 'owner', header: 'Owner', cell: () => null },
                ]
                render(
                    <DataTable
                        columns={counted}
                        data={data}
                        fullWidth
                        resizableColumns
                        onColumnSizingChange={onColumnSizingChange}
                    />
                )
                renderCell.mockClear()

                drag(screen.getByLabelText('Resize Name column'), [10, 20, 30])

                expect(renderCell).not.toHaveBeenCalled()
                expect(onColumnSizingChange).toHaveBeenCalledTimes(1)
                expect(onColumnSizingChange).toHaveBeenCalledWith({ name: 230 })
                expect(columnWidth(0)).toBe('230px')
            })

            it('moves the column in the DOM before the drag ends', () => {
                const onColumnSizingChange = jest.fn()
                render(
                    <DataTable
                        columns={columns}
                        data={data}
                        resizableColumns
                        columnSizing={{ name: 105 }}
                        onColumnSizingChange={onColumnSizingChange}
                    />
                )
                const grip = screen.getByLabelText('Resize Name column')

                act(() => {
                    grip.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 0, bubbles: true }))
                })
                act(() => {
                    grip.dispatchEvent(new MouseEvent('pointermove', { clientX: 2, bubbles: true }))
                })

                expect(columnWidth(0)).toBe('107px')
                expect(onColumnSizingChange).not.toHaveBeenCalled()
            })

            it('keeps a drag from leaving a width behind that holds the other columns back', () => {
                render(<DataTable columns={columns} data={data} resizableColumns columnSizing={{ name: 105 }} />)

                drag(screen.getByLabelText('Resize Name column'), [2])

                expect(screen.getByRole('table').style.minWidth).toBe('0')
            })

            it('leaves the layout alone on a click with no drag', () => {
                render(<DataTable columns={columns} data={data} resizableColumns />)

                drag(screen.getByLabelText('Resize Name column'), [])

                expect(screen.getByRole('table').getAttribute('data-layout')).toBeNull()
            })
        })

        // pinned: a resize changes the dragged column and no other. Never let another column absorb the difference.
        describe('changes only the dragged column', () => {
            const threeColumns: ColumnDef<TestRow>[] = [
                { accessorKey: 'name', header: 'Name', meta: { expand: true } },
                { id: 'owner', header: 'Owner', cell: () => null },
                { id: 'created', header: 'Created', cell: () => null },
            ]
            const widths = (): Record<string, string> =>
                Object.fromEntries(['Name', 'Owner', 'Created'].map((name, index) => [name, columnWidth(index)]))

            beforeEach(() => {
                jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
                    width: 200,
                } as DOMRect)
            })

            afterEach(() => {
                jest.restoreAllMocks()
            })

            it.each([
                ['shrinks the expand column', 'Name', 'ArrowLeft', { Name: '184px', Owner: '200px', Created: '200px' }],
                ['grows the expand column', 'Name', 'ArrowRight', { Name: '216px', Owner: '200px', Created: '200px' }],
                ['shrinks a middle column', 'Owner', 'ArrowLeft', { Name: '200px', Owner: '184px', Created: '200px' }],
                ['grows a middle column', 'Owner', 'ArrowRight', { Name: '200px', Owner: '216px', Created: '200px' }],
            ])('%s', (_name, column, key, expected) => {
                render(<DataTable columns={threeColumns} data={data} fullWidth resizableColumns />)

                fireEvent.keyDown(screen.getByLabelText(`Resize ${column} column`), { key })

                expect(widths()).toEqual(expected)
            })

            it('sets the table to the sum of its columns, so nothing has to give', () => {
                render(<DataTable columns={threeColumns} data={data} resizableColumns />)

                fireEvent.keyDown(screen.getByLabelText('Resize Owner column'), { key: 'ArrowLeft' })

                expect(screen.getByRole('table').style.width).toBe('584px')
            })

            it('fills the space left in a full-width table with an empty column', () => {
                render(<DataTable columns={threeColumns} data={data} fullWidth resizableColumns />)

                fireEvent.keyDown(screen.getByLabelText('Resize Owner column'), { key: 'ArrowLeft' })

                expect(screen.getByRole('table').style.minWidth).toBe('584px')
                expect(screen.getAllByRole('presentation')).toHaveLength(2)
            })
        })

        it('measures again when the set of columns changes', () => {
            jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 200 } as DOMRect)
            const { rerender } = render(<DataTable columns={columns} data={data} resizableColumns />)
            fireEvent.keyDown(resizer(), { key: 'ArrowRight' })
            expect(screen.getByRole('table').querySelectorAll('col')).toHaveLength(2)

            rerender(
                <DataTable
                    columns={[...columns, { id: 'added', header: 'Added', cell: () => null }]}
                    data={data}
                    resizableColumns
                    columnSizing={{ name: 105 }}
                />
            )

            expect(screen.getByRole('table').querySelectorAll('col')).toHaveLength(3)
            expect(columnWidth(2)).toBe('200px')
            jest.restoreAllMocks()
        })

        it('removes a column from the widths on a double click', () => {
            const onColumnSizingChange = jest.fn()
            render(
                <DataTable
                    columns={columns}
                    data={data}
                    resizableColumns
                    columnSizing={{ name: 105, other: 200 }}
                    onColumnSizingChange={onColumnSizingChange}
                />
            )

            fireEvent.doubleClick(resizer())

            expect(onColumnSizingChange).toHaveBeenCalledWith({ other: 200 })
        })
    })
})

import { type ColumnDef } from '@tanstack/react-table'
import { fireEvent, render, screen } from '@testing-library/react'

import { DataTable } from './data-table'

interface TestRow {
    name: string
}

const data: TestRow[] = [{ name: 'Ada' }]

describe('DataTable', () => {
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
})

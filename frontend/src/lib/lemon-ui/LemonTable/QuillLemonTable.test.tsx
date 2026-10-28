import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { QuillLemonTable } from './QuillLemonTable'
import { LemonTableColumns } from './types'

interface Row {
    name: string
    value: number
}

const DATA: Row[] = [
    { name: 'alpha', value: 3 },
    { name: 'beta', value: 1 },
    { name: 'gamma', value: 2 },
]

describe('QuillLemonTable', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    it.each([
        {
            sorter: (a: Row, b: Row) => a.value - b.value,
            defaultSortOrder: undefined,
            expectedOrder: ['beta', 'gamma', 'alpha'],
            expectedSorting: { columnKey: 'value', order: 1 },
        },
        {
            sorter: (a: Row, b: Row) => a.value - b.value,
            defaultSortOrder: -1 as const,
            expectedOrder: ['alpha', 'gamma', 'beta'],
            expectedSorting: { columnKey: 'value', order: -1 },
        },
        {
            sorter: true as const,
            defaultSortOrder: undefined,
            expectedOrder: ['alpha', 'beta', 'gamma'],
            expectedSorting: { columnKey: 'value', order: 1 },
        },
    ])(
        'sorts like LemonTable on a header click (sorter $sorter, default order $defaultSortOrder)',
        ({ sorter, defaultSortOrder, expectedOrder, expectedSorting }) => {
            const onSort = jest.fn()
            const columns: LemonTableColumns<Row> = [
                {
                    title: 'Value',
                    key: 'value',
                    render: (_, row) => <span data-attr="cell-name">{row.name}</span>,
                    sorter,
                    defaultSortOrder,
                },
            ]
            render(<QuillLemonTable columns={columns} dataSource={DATA} onSort={onSort} useURLForSorting={false} />)

            fireEvent.click(screen.getByText('Value'))

            expect(onSort).toHaveBeenCalledWith(expectedSorting)
            expect(screen.getAllByTestId('cell-name').map((el) => el.textContent)).toEqual(expectedOrder)
        }
    )
})

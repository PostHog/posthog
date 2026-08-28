import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { LemonTable } from './LemonTable'

interface Row {
    id: number
    name: string
    value: number
}

const DATA: Row[] = [
    { id: 1, name: 'alpha', value: 3 },
    { id: 2, name: 'beta', value: 1 },
    { id: 3, name: 'gamma', value: 2 },
]

const COLUMNS = [
    {
        title: 'Value',
        key: 'value',
        render: (_: any, row: Row) => <span data-attr="cell-name">{row.name}</span>,
        sorter: (a: Row, b: Row) => a.value - b.value,
    },
]

describe('LemonTable', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    const renderedOrder = (): string[] => screen.getAllByTestId('cell-name').map((el) => el.textContent ?? '')

    it.each([
        [true, ['alpha', 'gamma', 'beta']],
        [false, ['alpha', 'beta', 'gamma']],
    ])('useURLForSorting=%s reads the order search param only when enabled', (useURLForSorting, expectedOrder) => {
        router.actions.push(router.values.location.pathname, { order: '-value' })
        render(
            <LemonTable
                rowKey="id"
                dataSource={DATA}
                columns={COLUMNS}
                useURLForSorting={useURLForSorting as boolean}
            />
        )
        expect(renderedOrder()).toEqual(expectedOrder)
    })

    it('keeps headers, expanded rows, and empty states aligned when the row expansion toggle is hidden', () => {
        const { rerender } = render(
            <LemonTable
                rowKey="id"
                dataSource={DATA}
                columns={COLUMNS}
                expandable={{
                    expandedRowRender: () => <div>Expanded</div>,
                    isRowExpanded: () => true,
                    showRowExpansionToggle: false,
                    noIndent: true,
                }}
            />
        )

        const headerCells = document.querySelectorAll('thead tr:last-child th')
        const firstRowCells = document.querySelectorAll('tbody tr:first-child > td')
        const expansionCells = document.querySelectorAll('tbody tr.LemonTable__expansion > td')

        expect(headerCells).toHaveLength(1)
        expect(firstRowCells).toHaveLength(1)
        expect(firstRowCells[0]).toHaveTextContent('alpha')
        expect(expansionCells).toHaveLength(3)
        expect(expansionCells[0]).toHaveAttribute('colspan', '1')

        rerender(
            <LemonTable
                rowKey="id"
                dataSource={[]}
                columns={COLUMNS}
                expandable={{
                    expandedRowRender: () => <div>Expanded</div>,
                    showRowExpansionToggle: false,
                }}
            />
        )

        expect(document.querySelector('tbody tr.LemonTable__empty-state > td')).toHaveAttribute('colspan', '1')
    })

    it('keeps group headers aligned when the sticky first group has a single column', () => {
        // The sticky-first-group header is rendered as a title cell plus a filler cell. With one child
        // the filler's colSpan would be 0, which the DOM clamps to 1, adding a phantom column that
        // shifts every following group title one column to the right.
        render(
            <LemonTable
                rowKey="id"
                dataSource={DATA}
                firstColumnSticky
                columns={[
                    { children: [{ title: 'Name', key: 'name', dataIndex: 'name' as keyof Row }] },
                    {
                        title: 'Metrics',
                        children: [
                            { title: 'Value', key: 'value', dataIndex: 'value' as keyof Row },
                            { title: 'Id', key: 'id', dataIndex: 'id' as keyof Row },
                        ],
                    },
                ]}
            />
        )
        const groupingRow = document.querySelector('tr.LemonTable__row--grouping')!
        const spannedColumns = Array.from(groupingRow.querySelectorAll('th')).reduce((sum, th) => sum + th.colSpan, 0)
        expect(spannedColumns).toBe(3)
    })
})

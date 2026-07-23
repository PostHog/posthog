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
})

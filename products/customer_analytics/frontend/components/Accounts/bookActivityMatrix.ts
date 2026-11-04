import type { DotMatrixCell } from 'lib/components/DotMatrix/types'
import { dayjs } from 'lib/dayjs'

import type { BookActivityMatrixResult } from '~/queries/schema/schema-general'

import type { AccountActivityMatrixDatum, AccountActivityMatrixProps } from './accountActivityMatrix'

export function getBookActivityMatrixProps(
    result: BookActivityMatrixResult,
    selectedSeries: string[]
): AccountActivityMatrixProps {
    const combinations = new Map<string, BookActivityMatrixResult['combinations']>()
    for (const combination of result.combinations) {
        const key = JSON.stringify([combination.row, combination.column])
        const cell = combinations.get(key) ?? []
        cell.push(combination)
        combinations.set(key, cell)
    }
    const bits = new Map(result.series.map(({ key }, index) => [key, 2 ** index]))
    const aggregateSelection = (cell: DotMatrixCell<AccountActivityMatrixDatum>, selected: string[]): number => {
        const mask = selected.reduce((mask, key) => mask | (bits.get(key) ?? 0), 0)
        return (combinations.get(JSON.stringify([cell.rowKey, cell.columnKey])) ?? []).reduce(
            (total, combination) => total + (combination.mask & mask ? combination.users : 0),
            0
        )
    }
    return {
        data: result.data.map(({ users, ...cell }) => ({ ...cell, value: users })),
        fields: { row: 'row', column: 'column', series: 'series', value: 'value' },
        rows: result.rows,
        columns: result.columns.map((column) => ({ ...column, label: dayjs(column.key).format('MMM D') })),
        series: result.series.map((series, index) => ({ ...series, color: `var(--data-color-${(index % 15) + 1})` })),
        aggregateSelection,
        rowHeader: { title: 'Account' },
        sizeThresholds: [1, 5, 20],
        legend: {
            itemLabel: 'product',
            selectionLabel: (count, mode) =>
                mode === 'count'
                    ? `Users of ${count} selected ${count === 1 ? 'product' : 'products'}`
                    : `Showing ${count} ${count === 1 ? 'product' : 'products'}`,
            valueLabel: 'Users',
            countLabel: selectedSeries.length ? 'Users of selected products' : 'Products used',
        },
    }
}

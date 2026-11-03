import type { DotMatrixAxisItem } from '../types'
import {
    DOT_MATRIX_MOCK_ACCOUNTS,
    DOT_MATRIX_MOCK_COLUMNS,
    DOT_MATRIX_MOCK_GROUPS,
    DOT_MATRIX_MOCK_PRODUCTS,
    DOT_MATRIX_USER_COUNT_SCALE,
} from './dotMatrixMockFixtures'
import type { DotMatrixMockAccount, DotMatrixMockDataset, DotMatrixMockDatum } from './dotMatrixMockTypes'
import { aggregateDotMatrixMockPeople, getDotMatrixMockPeople } from './mocks'

export function getDotMatrixAccountMeta(
    account: DotMatrixMockAccount,
    data: DotMatrixMockDatum[],
    selected: string[]
): string {
    if (selected.length > 0) {
        const people = getDotMatrixMockPeople(
            data.filter((datum) => datum.rowKey === account.id),
            selected
        )
        const productLabel =
            selected.length === 1
                ? DOT_MATRIX_MOCK_PRODUCTS.find(([key]) => key === selected[0])?.[1]
                : `these ${selected.length} products`
        return people.length ? `${people.length} users of ${productLabel}` : 'No use in range'
    }
    const accountData = data.filter((datum) => datum.rowKey === account.id && datum.value > 0)
    const products = new Set(accountData.map((datum) => datum.seriesKey)).size
    const people = getDotMatrixMockPeople(accountData).length
    return `${products} products · ${people} users`
}

export function getDotMatrixDetailDataset(
    data: DotMatrixMockDatum[],
    selected: string[],
    accountOnly = false,
    selectedAccount = 'acme'
): DotMatrixMockDataset {
    const accounts = accountOnly
        ? DOT_MATRIX_MOCK_ACCOUNTS.filter((account) => account.id === selectedAccount)
        : DOT_MATRIX_MOCK_ACCOUNTS.slice(0, 2)
    const rows: DotMatrixAxisItem[] = []
    const result: DotMatrixMockDatum[] = []
    for (const account of accounts) {
        if (accountOnly) {
            rows.push({ key: 'summary', label: 'Products used', group: 'summary' })
            for (const column of DOT_MATRIX_MOCK_COLUMNS) {
                result.push({
                    rowKey: 'summary',
                    columnKey: column.key,
                    seriesKey: '',
                    value: data.filter(
                        (datum) => datum.rowKey === account.id && datum.columnKey === column.key && datum.value > 0
                    ).length,
                    persons: [],
                })
            }
        }
        if (!accountOnly) {
            rows.push({ key: account.id, label: account.name, group: 'account' })
            for (const column of DOT_MATRIX_MOCK_COLUMNS) {
                const cellData = data.filter((datum) => datum.rowKey === account.id && datum.columnKey === column.key)
                result.push({
                    rowKey: account.id,
                    columnKey: column.key,
                    seriesKey: '',
                    value: selected.length
                        ? aggregateDotMatrixMockPeople(
                              { rowKey: account.id, columnKey: column.key, values: {}, data: cellData },
                              selected
                          )
                        : cellData.filter((datum) => datum.value > 0).length,
                    persons: [],
                })
            }
        }
        DOT_MATRIX_MOCK_GROUPS.forEach((group, groupIndex) => {
            const products = DOT_MATRIX_MOCK_PRODUCTS.slice(groupIndex * 6, groupIndex * 6 + 6).filter(
                ([product]) =>
                    account.u[product]?.some((value) => value > 0) && (!selected.length || selected.includes(product))
            )
            if (accountOnly && products.length) {
                rows.push({ key: `group:${group.key}`, label: group.label, group: 'family' })
            }
            for (const [product, label] of products) {
                const rowKey = `${account.id}/${product}`
                rows.push({ key: rowKey, label, group: group.key })
                result.push(
                    ...data
                        .filter((datum) => datum.rowKey === account.id && datum.seriesKey === product)
                        .map((datum) => ({ ...datum, rowKey, seriesKey: '' }))
                )
            }
        })
    }
    return {
        data: result,
        fields: { row: 'rowKey', column: 'columnKey', value: 'value' },
        rows,
        columns: DOT_MATRIX_MOCK_COLUMNS,
        mode: 'count',
        countOf: 'value',
        countScale: DOT_MATRIX_USER_COUNT_SCALE,
        legend: false,
        rowHeader: { title: accountOnly ? 'Product' : 'Account and product' },
        cellWidth: accountOnly ? 64 : 110,
    }
}

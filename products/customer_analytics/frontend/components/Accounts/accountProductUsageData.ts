import type { DotMatrixAxisItem, DotMatrixProps } from 'lib/components/DotMatrix/types'
import { dayjs } from 'lib/dayjs'

import type { BookActivityMatrixResult } from '~/queries/schema/schema-general'

import { getProductUsageGrouping } from '../ProductActivity/productUsagePresentation'

export interface AccountProductUsageRow extends DotMatrixAxisItem {
    kind: 'summary' | 'group' | 'product'
    productKey?: string
    color?: string
}

export type AccountProductUsageDatum = { row: string; column: string; series: string; value: number }

export function getAccountProductUsageProps(
    result: BookActivityMatrixResult,
    accountId: string,
    grouping: string
): Omit<DotMatrixProps<AccountProductUsageDatum>, 'rows'> & { rows: AccountProductUsageRow[] } {
    const presentation = getProductUsageGrouping(result.series, result.groupings, grouping)
    const products = new Map(presentation.series.map((product) => [product.key, product]))
    const rows: AccountProductUsageRow[] = [{ key: 'summary', label: 'Products used', kind: 'summary' }]
    const cells = new Map<string, Map<string, number>>()
    for (const cell of result.data) {
        if (cell.row === accountId) {
            const values = cells.get(cell.column) ?? new Map<string, number>()
            values.set(cell.series, cell.users)
            cells.set(cell.column, values)
        }
    }
    const data: AccountProductUsageDatum[] = result.columns.map(({ key }) => ({
        row: 'summary',
        column: key,
        series: 'summary',
        value: [...(cells.get(key)?.values() ?? [])].filter((value) => value > 0).length,
    }))
    const active = new Set(
        result.data.filter((cell) => cell.row === accountId && cell.users > 0).map((cell) => cell.series)
    )
    for (const group of presentation.groups) {
        const items = (group.items ?? []).filter((key) => active.has(key))
        if (!items.length) {
            continue
        }
        rows.push({ key: `group:${group.key}`, label: group.label, kind: 'group', color: group.color })
        for (const productKey of items) {
            const product = products.get(productKey)!
            const rowKey = JSON.stringify([group.key, productKey])
            rows.push({ key: rowKey, label: product.label, kind: 'product', productKey, color: product.color })
            for (const column of result.columns) {
                data.push({
                    row: rowKey,
                    column: column.key,
                    series: productKey,
                    value: cells.get(column.key)?.get(productKey) ?? 0,
                })
            }
        }
    }
    return {
        rows: cells.size ? rows : [],
        data: cells.size ? data : [],
        fields: { row: 'row', column: 'column', series: 'series', value: 'value' },
        columns: result.columns.map((column) => ({ ...column, label: dayjs(column.key).format('MMM D') })),
        series: presentation.series,
        legend: false,
        mode: 'count',
        countOf: 'value',
        rowHeader: { title: 'Product', width: 190 },
        cellWidth: 62,
    }
}

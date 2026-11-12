import { DOT_MATRIX_SIZE_THRESHOLDS } from 'lib/components/DotMatrix/dotMatrixPresentation'
import type { DotMatrixCell } from 'lib/components/DotMatrix/types'
import { dayjs } from 'lib/dayjs'

import type { BookActivityMatrixResult } from '~/queries/schema/schema-general'

import type { ActivityMatrixDatum, ActivityMatrixProps } from '../ProductActivity/activityMatrixTypes'
import { getActivityCombinationUsers, getActivitySelectionMask } from '../ProductActivity/activityUserCounts'
import {
    getProductUsageGrouping,
    getProductUsageCountLabel,
    getProductUsageCountScale,
} from '../ProductActivity/productUsagePresentation'

export function getBookActivityMatrixProps(
    result: BookActivityMatrixResult,
    selectedSeries: string[]
): ActivityMatrixProps {
    const combinations = new Map<string, BookActivityMatrixResult['combinations']>()
    for (const combination of result.combinations) {
        const key = JSON.stringify([combination.row, combination.column])
        const cell = combinations.get(key) ?? []
        cell.push(combination)
        combinations.set(key, cell)
    }
    const aggregateSelection = (cell: DotMatrixCell<ActivityMatrixDatum>, selected: string[]): number => {
        const mask = getActivitySelectionMask(result.series, selected)
        return (combinations.get(JSON.stringify([cell.rowKey, cell.columnKey])) ?? []).reduce(
            (total, combination) => total + getActivityCombinationUsers(combination, mask),
            0
        )
    }
    return {
        data: result.data.map(({ users, ...cell }) => ({ ...cell, value: users })),
        fields: { row: 'row', column: 'column', series: 'series', value: 'value' },
        rows: result.rows,
        columns: result.columns.map((column) => ({ ...column, label: dayjs(column.key).format('MMM D') })),
        ...getProductUsageGrouping(result.series, result.groupings, 'role'),
        countScale: getProductUsageCountScale(selectedSeries.length > 0),
        aggregateSelection,
        rowHeader: { title: 'Account' },
        sizeThresholds: DOT_MATRIX_SIZE_THRESHOLDS,
        legend: {
            itemLabel: 'product',
            selectionLabel: (count, mode) =>
                mode === 'count'
                    ? `Users of ${count} selected ${count === 1 ? 'product' : 'products'}`
                    : `Showing ${count} ${count === 1 ? 'product' : 'products'}`,
            valueLabel: 'Users',
            countLabel: getProductUsageCountLabel(result.series, selectedSeries),
        },
    }
}

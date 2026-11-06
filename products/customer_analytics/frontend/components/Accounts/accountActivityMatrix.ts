import type { DotMatrixCell } from 'lib/components/DotMatrix/types'
import { dayjs } from 'lib/dayjs'

import type { AccountActivityMatrixResult } from '~/queries/schema/schema-general'

import type { ActivityMatrixDatum, ActivityMatrixProps } from '../ProductActivity/activityMatrixTypes'

const SERIES_COLOR_COUNT = 15

export const EMPTY_ACCOUNT_ACTIVITY_MATRIX: AccountActivityMatrixResult = {
    rows: [],
    columns: [],
    series: [],
    data: [],
    truncated: false,
    skippedMetricIds: [],
}

export function countActiveInSelection(cell: DotMatrixCell<ActivityMatrixDatum>, selected: string[]): number {
    return selected.some((key) => (cell.values[key] ?? 0) > 0) ? 1 : 0
}

export function getAccountActivityMatrixProps(
    result: AccountActivityMatrixResult,
    selectedSeries: string[]
): ActivityMatrixProps {
    const smallestValue = result.data.reduce(
        (smallest, { value }) => (value > 0 ? Math.min(smallest, value) : smallest),
        1
    )
    return {
        data: result.data.map((cell) => ({ ...cell })),
        fields: { row: 'row', column: 'column', series: 'series', value: 'value' },
        rows: result.rows.map(({ key, label }) => ({ key, label })),
        columns: result.columns.map(({ key, partial }) => ({ key, partial, label: dayjs(key).format('MMM D') })),
        series: result.series.map(({ key, label }, index) => ({
            key,
            label,
            color: `var(--data-color-${(index % SERIES_COLOR_COUNT) + 1})`,
        })),
        aggregateSelection: countActiveInSelection,
        sizeThresholds: [smallestValue, 5, 10],
        rowHeader: { title: 'Person' },
        legend: {
            itemLabel: 'metric',
            valueLabel: 'Value',
            countLabel: selectedSeries.length ? 'Active in selected metrics' : 'Metrics used',
        },
    }
}

export function keepKnownSeries(selectedSeries: string[], result: AccountActivityMatrixResult | null): string[] {
    if (!result) {
        return selectedSeries
    }
    const known = new Set(result.series.map(({ key }) => key))
    return selectedSeries.filter((key) => known.has(key))
}

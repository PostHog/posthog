import { dayjs } from 'lib/dayjs'

import type {
    BookActivityMatrixResult,
    BookActivityMatrixFirstUse,
    BookActivityInterval,
} from '~/queries/schema/schema-general'

import { productUsageCount } from './productUsageData'
import { getProductUsageFirstSeries } from './productUsagePresentation'

export function ProductUsageCellTooltip({
    matrix,
    rowKey,
    columnKey,
    values,
    selected,
    interval,
    firstUse = [],
}: {
    matrix: BookActivityMatrixResult
    rowKey: string
    columnKey: string
    values: Record<string, number>
    selected: string[]
    interval: BookActivityInterval
    firstUse?: BookActivityMatrixFirstUse[]
}): JSX.Element {
    const used = matrix.series
        .filter((product) => values[product.key] > 0 && (!selected.length || selected.includes(product.key)))
        .sort((a, b) => values[b.key] - values[a.key])
    const firsts = new Set(getProductUsageFirstSeries(firstUse, rowKey, columnKey, interval))
    const start = dayjs(columnKey)
    const end = start.add(1, interval).subtract(1, 'day')
    const partial = matrix.columns.find((column) => column.key === columnKey)?.partial
    const period =
        interval === 'day'
            ? start.format('MMM D, YYYY')
            : `${interval === 'week' ? 'Week' : 'Month'} of ${start.format('MMM D')} to ${end.format('MMM D, YYYY')}`
    return (
        <div className="flex flex-col gap-2 min-w-56">
            <strong>{matrix.rows.find((row) => row.key === rowKey)?.label ?? rowKey}</strong>
            <span className="text-xs">{`${period}${partial ? ' (to date)' : ''}. ${used.length} ${used.length === 1 ? 'product' : 'products'} used`}</span>
            {used.map((product) => (
                <div className="flex gap-3 justify-between" key={product.key}>
                    <span>{`${product.label}${firsts.has(product.key) ? ' · First use ever' : ''}`}</span>
                    <span>{`${values[product.key]} users`}</span>
                </div>
            ))}
            {selected.length > 1 && (
                <strong>{`${productUsageCount(matrix, rowKey, columnKey, selected)} distinct users across selected products`}</strong>
            )}
            <span className="text-xs text-secondary">Click to zoom in</span>
        </div>
    )
}

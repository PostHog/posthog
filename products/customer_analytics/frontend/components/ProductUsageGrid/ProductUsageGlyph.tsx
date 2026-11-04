import { DotGlyph } from 'lib/components/DotMatrix/DotGlyph'

import type {
    BookActivityInterval,
    BookActivityMatrixFirstUse,
    BookActivityMatrixResult,
} from '~/queries/schema/schema-general'

import { getProductUsageFirstSeries, getProductUsageGrouping } from './productUsagePresentation'

export function ProductUsageGlyph({
    result,
    rowKey,
    columnKey,
    grouping,
    firstUse = [],
    interval = 'week',
    values: suppliedValues,
    hoveredSeries,
}: {
    result: BookActivityMatrixResult
    rowKey: string
    columnKey: string
    grouping: string
    firstUse?: BookActivityMatrixFirstUse[]
    interval?: BookActivityInterval
    values?: Record<string, number>
    hoveredSeries?: string | null
}): JSX.Element {
    const presentation = getProductUsageGrouping(result.series, result.groupings, grouping)
    const values =
        suppliedValues ??
        Object.fromEntries(
            result.data
                .filter((cell) => cell.row === rowKey && cell.column === columnKey)
                .map(({ series, users }) => [series, users])
        )
    return (
        <DotGlyph
            {...presentation}
            values={values}
            cellPitch={grouping === 'usecase' ? 13 : 17}
            hoveredSeries={hoveredSeries}
            firstUseSeries={getProductUsageFirstSeries(firstUse, rowKey, columnKey, interval)}
            sizeThresholds={[1, 5, 10]}
            label={`${result.rows.find(({ key }) => key === rowKey)?.label ?? rowKey}, ${columnKey}`}
        />
    )
}

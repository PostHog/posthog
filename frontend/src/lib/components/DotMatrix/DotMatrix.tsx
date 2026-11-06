import './DotMatrix.scss'

import clsx from 'clsx'
import { useMemo, useState } from 'react'

import { normalizeDotMatrixCountScale, normalizeDotMatrixData, normalizeDotMatrixSizeThresholds } from './dotMatrixData'
import { DotMatrixLegend } from './DotMatrixLegend'
import { DOT_MATRIX_EMPTY_GROUPS, DOT_MATRIX_SIZE_THRESHOLDS, resolveDotMatrixSeries } from './dotMatrixPresentation'
import { DotMatrixTable } from './DotMatrixTable'
import type { DotMatrixProps } from './types'

export function DotMatrix<D extends Record<string, unknown>>({
    data,
    fields,
    rows,
    columns,
    series,
    groups = DOT_MATRIX_EMPTY_GROUPS,
    columnsPerGroup,
    firstUseSeries,
    mode = fields.series !== undefined ? 'dots' : 'count',
    sizeThresholds = DOT_MATRIX_SIZE_THRESHOLDS,
    countScale,
    countOf = fields.series !== undefined ? 'activeSeries' : 'value',
    selectedSeries = [],
    onSelectedSeriesChange,
    aggregateSelection,
    rowHeader,
    trailingColumns,
    renderCell,
    renderTooltip,
    tooltipInteractive,
    onCellClick,
    cellWidth = mode === 'dots' ? 110 : 64,
    rowClassName,
    className,
    legend,
    loading = false,
    emptyState = 'No data to display. Add data to see the matrix.',
    pageSize,
}: DotMatrixProps<D>): JSX.Element {
    const [hoveredSeries, setHoveredSeries] = useState<string | null>(null)
    const matrix = useMemo(
        () => normalizeDotMatrixData({ data, fields, rows, columns, series }),
        [data, fields, rows, columns, series]
    )
    const resolvedSizeThresholds = useMemo(() => normalizeDotMatrixSizeThresholds(sizeThresholds), [sizeThresholds])
    const resolvedCountScale = useMemo(() => countScale && normalizeDotMatrixCountScale(countScale), [countScale])
    const coloredSeries = useMemo(() => resolveDotMatrixSeries(matrix.series, groups), [matrix.series, groups])
    const cellOptions = {
        mode,
        series: coloredSeries,
        groups,
        hoveredSeries,
        columnsPerGroup,
        firstUseSeries,
        sizeThresholds: resolvedSizeThresholds,
        countScale: resolvedCountScale,
        countOf,
        selectedSeries,
        aggregateSelection,
        renderCell,
        renderTooltip,
        tooltipInteractive,
        onCellClick,
    }

    return (
        <div className={clsx('DotMatrix', `DotMatrix--${mode}`, className)}>
            {legend !== false && coloredSeries.length > 0 && (
                <DotMatrixLegend
                    series={coloredSeries}
                    groups={groups}
                    mode={mode}
                    sizeThresholds={resolvedSizeThresholds}
                    countScale={resolvedCountScale}
                    selectedSeries={selectedSeries}
                    onSelectedSeriesChange={onSelectedSeriesChange}
                    labels={legend}
                    hoveredSeries={hoveredSeries}
                    onHoveredSeriesChange={setHoveredSeries}
                />
            )}
            <DotMatrixTable
                matrix={matrix}
                cellWidth={cellWidth}
                cellOptions={cellOptions}
                rowHeader={rowHeader}
                trailingColumns={trailingColumns}
                rowClassName={rowClassName}
                loading={loading}
                emptyState={emptyState}
                pageSize={pageSize}
            />
        </div>
    )
}

import './DotGlyph.scss'

import { useMemo } from 'react'

import { normalizeDotMatrixSizeThresholds } from './dotMatrixData'
import {
    DOT_MATRIX_EMPTY_GROUPS,
    DOT_MATRIX_SIZE_THRESHOLDS,
    getDotMatrixActiveSeries,
    getDotMatrixGroups,
    resolveDotMatrixSeries,
} from './dotMatrixPresentation'
import { DotMatrixSymbol } from './DotMatrixSymbol'
import type { DotMatrixGroup, DotMatrixSeries } from './types'

interface DotGlyphProps {
    series: DotMatrixSeries[]
    values: Record<string, number>
    groups?: DotMatrixGroup[]
    sizeThresholds?: number[]
    label: string
    columnsPerGroup?: number
    firstUseSeries?: string[]
}

export function DotGlyph({
    series,
    values,
    groups = DOT_MATRIX_EMPTY_GROUPS,
    sizeThresholds = DOT_MATRIX_SIZE_THRESHOLDS,
    label,
    columnsPerGroup = 6,
    firstUseSeries = [],
}: DotGlyphProps): JSX.Element {
    const thresholds = useMemo(() => normalizeDotMatrixSizeThresholds(sizeThresholds), [sizeThresholds])
    const coloredSeries = useMemo(() => resolveDotMatrixSeries(series, groups), [series, groups])
    const perRow = Number.isFinite(columnsPerGroup) ? Math.max(1, Math.floor(columnsPerGroup)) : 6
    const rows = getDotMatrixGroups(coloredSeries, groups).map((group) => group.series)
    const rowCount = rows.reduce((total, items) => total + Math.max(1, Math.ceil(items.length / perRow)), 0)
    const width = perRow * 17
    const height = Math.max(1, rowCount) * 17
    const valueLabel = getDotMatrixActiveSeries(series, values)
        .map(
            ({ key, label }) =>
                `${label ?? key} ${values[key]}${firstUseSeries.includes(key) ? ', first use ever' : ''}`
        )
        .join(', ')
    let rowOffset = 0

    return (
        <svg
            className="DotGlyph"
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label={`${label}: ${valueLabel || 'No values'}`}
        >
            {rows.map((items, groupIndex) => {
                const firstRow = rowOffset
                rowOffset += Math.max(1, Math.ceil(items.length / perRow))

                return items.map((item, index) => {
                    const value = values[item.key] ?? 0
                    const cx = 8.5 + (index % perRow) * 17
                    const cy = 8.5 + (firstRow + Math.floor(index / perRow)) * 17

                    return (
                        <DotMatrixSymbol
                            key={`${groupIndex}:${item.key}`}
                            cx={cx}
                            cy={cy}
                            value={value}
                            firstUse={firstUseSeries.includes(item.key)}
                            thresholds={thresholds}
                            color={item.color}
                        />
                    )
                })
            })}
        </svg>
    )
}

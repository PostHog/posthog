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
    cellPitch?: 13 | 17
    hoveredSeries?: string | null
}

export function DotGlyph({
    series,
    values,
    groups = DOT_MATRIX_EMPTY_GROUPS,
    sizeThresholds = DOT_MATRIX_SIZE_THRESHOLDS,
    label,
    columnsPerGroup = 6,
    firstUseSeries = [],
    cellPitch = 17,
    hoveredSeries = null,
}: DotGlyphProps): JSX.Element {
    const thresholds = useMemo(() => normalizeDotMatrixSizeThresholds(sizeThresholds), [sizeThresholds])
    const coloredSeries = useMemo(() => resolveDotMatrixSeries(series, groups), [series, groups])
    const perRow = Number.isFinite(columnsPerGroup) ? Math.max(1, Math.floor(columnsPerGroup)) : 6
    const rows = getDotMatrixGroups(coloredSeries, groups).map((group) => group.series)
    const rowCount = rows.reduce((total, items) => total + Math.max(1, Math.ceil(items.length / perRow)), 0)
    const width = perRow * cellPitch
    const height = Math.max(1, rowCount) * cellPitch
    const valueLabel = getDotMatrixActiveSeries(series, values)
        .map(
            ({ key, label }) =>
                `${label ?? key} ${values[key]}${firstUseSeries.includes(key) ? ', first use ever' : ''}`
        )
        .join(', ')
    let rowOffset = 0

    return (
        <svg
            className={`DotGlyph${cellPitch === 13 ? ' DotGlyph--compact' : ''}`}
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
                    const cx = cellPitch / 2 + (index % perRow) * cellPitch
                    const cy = cellPitch / 2 + (firstRow + Math.floor(index / perRow)) * cellPitch

                    return (
                        <g
                            key={`${groupIndex}:${item.key}`}
                            data-series={item.key}
                            opacity={hoveredSeries && hoveredSeries !== item.key ? 0.25 : 1}
                            transform={`translate(${cx} ${cy}) scale(${cellPitch / 17}) translate(${-cx} ${-cy})`}
                        >
                            <DotMatrixSymbol
                                cx={cx}
                                cy={cy}
                                value={value}
                                firstUse={firstUseSeries.includes(item.key)}
                                thresholds={thresholds}
                                color={item.color}
                            />
                        </g>
                    )
                })
            })}
        </svg>
    )
}

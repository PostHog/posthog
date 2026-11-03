import './DotGlyph.scss'

import { Fragment } from 'react'

import type { DotMatrixGroup, DotMatrixSeries } from './types'

interface DotGlyphProps {
    series: DotMatrixSeries[]
    values: Record<string, number>
    groups?: DotMatrixGroup[]
    sizeThresholds?: number[]
    label: string
    columnsPerGroup?: number
}

export function DotGlyph({
    series,
    values,
    groups = [],
    sizeThresholds = [1, 5, 10],
    label,
    columnsPerGroup = 6,
}: DotGlyphProps): JSX.Element {
    const perRow = Number.isFinite(columnsPerGroup) ? Math.max(1, Math.floor(columnsPerGroup)) : 6
    const groupKeys = Array.from(new Set([...groups.map(({ key }) => key), ...series.map(({ group }) => group)]))
    const rows = groupKeys.map((key) => series.filter(({ group }) => group === key))
    const rowCount = rows.reduce((total, items) => total + Math.max(1, Math.ceil(items.length / perRow)), 0)
    const width = perRow * 17
    const height = Math.max(1, rowCount) * 17
    const valueLabel = series
        .filter(({ key }) => Number.isFinite(values[key]) && values[key] > 0)
        .map(({ key, label }) => `${label ?? key} ${values[key]}`)
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
                const groupColor = groups.find(({ key }) => key === groupKeys[groupIndex])?.color

                return items.map((item, index) => {
                    const value = values[item.key] ?? 0
                    const cx = 8.5 + (index % perRow) * 17
                    const cy = 8.5 + (firstRow + Math.floor(index / perRow)) * 17
                    const color = item.color ?? groupColor ?? `var(--data-color-${(groupIndex % 15) + 1})`

                    return (
                        <Fragment key={item.key}>
                            {Number.isFinite(value) && value >= (sizeThresholds[0] ?? 1) && value > 0 && (
                                <circle cx={cx} cy={cy} r={2.6} fill={color} />
                            )}
                            {Number.isFinite(value) && value >= (sizeThresholds[1] ?? 5) && value > 0 && (
                                <circle cx={cx} cy={cy} r={4.4} fill="none" stroke={color} strokeWidth={1.2} />
                            )}
                            {Number.isFinite(value) && value >= (sizeThresholds[2] ?? 10) && value > 0 && (
                                <circle cx={cx} cy={cy} r={6.7} fill="none" stroke={color} strokeWidth={1.2} />
                            )}
                        </Fragment>
                    )
                })
            })}
        </svg>
    )
}

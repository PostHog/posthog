import { useMemo } from 'react'

import type { HeatmapProps } from '../types'
import { interpolateColor } from '../utils/color'
import { formatValue } from '../utils/format'
import { mergeTheme } from '../utils/theme'

export function Heatmap(props: HeatmapProps): JSX.Element {
    const { data, xLabels, yLabels, showValues = true, borderRadius = 2 } = props
    const theme = mergeTheme(props.theme)
    const colorRange = props.colorRange ?? [theme.gridColor ?? '#eee', theme.colors[0]]

    const { grid, minVal, maxVal } = useMemo(() => {
        const g: Map<string, number> = new Map()
        let min = Infinity
        let max = -Infinity
        for (const cell of data) {
            const key = `${cell.x}|${cell.y}`
            g.set(key, cell.value)
            if (cell.value < min) {
                min = cell.value
            }
            if (cell.value > max) {
                max = cell.value
            }
        }
        return { grid: g, minVal: min, maxVal: max }
    }, [data])

    const style: React.CSSProperties = {
        width: typeof props.width === 'number' ? `${props.width}px` : (props.width ?? '100%'),
        height: typeof props.height === 'number' ? `${props.height}px` : (props.height ?? 'auto'),
        fontFamily: theme.fontFamily,
        fontSize: theme.fontSize,
        overflow: 'auto',
    }

    const cellSize = Math.max(24, Math.floor(600 / Math.max(xLabels.length, 1)))

    return (
        <div className={props.className} style={style} role="figure" aria-label={props.ariaLabel ?? 'Heatmap'}>
            <div style={{ display: 'inline-block' }}>
                <div style={{ display: 'flex', marginLeft: 80 }}>
                    {xLabels.map((xl) => (
                        <div
                            key={xl}
                            style={{
                                width: cellSize,
                                textAlign: 'center',
                                color: theme.axisColor,
                                fontSize: (theme.fontSize ?? 12) - 1,
                                padding: '2px 0',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                            }}
                        >
                            {xl}
                        </div>
                    ))}
                </div>
                {yLabels.map((yl) => (
                    <div key={yl} style={{ display: 'flex', alignItems: 'center' }}>
                        <div
                            style={{
                                width: 80,
                                flexShrink: 0,
                                textAlign: 'right',
                                paddingRight: 8,
                                color: theme.axisColor,
                                fontSize: (theme.fontSize ?? 12) - 1,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                            }}
                        >
                            {yl}
                        </div>
                        {xLabels.map((xl) => {
                            const val = grid.get(`${xl}|${yl}`) ?? 0
                            const bg = interpolateColor(colorRange, val, minVal, maxVal)
                            const textColor = val > (minVal + maxVal) / 2 ? '#fff' : theme.axisColor
                            return (
                                <div
                                    key={xl}
                                    style={{
                                        width: cellSize,
                                        height: cellSize,
                                        backgroundColor: bg,
                                        borderRadius,
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        margin: 1,
                                        color: textColor ?? undefined,
                                        fontSize: (theme.fontSize ?? 12) - 2,
                                    }}
                                    title={`${xl}, ${yl}: ${val}`}
                                >
                                    {showValues ? formatValue(val, 'compact') : ''}
                                </div>
                            )
                        })}
                    </div>
                ))}
            </div>
        </div>
    )
}

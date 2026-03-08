import { useMemo } from 'react'

import { formatValue } from '../format'
import { mergeTheme } from '../theme'
import type { HeatmapProps } from '../types'

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
        width: typeof props.width === 'number' ? `${props.width}px` : props.width ?? '100%',
        height: typeof props.height === 'number' ? `${props.height}px` : props.height ?? 'auto',
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

function interpolateColor(range: string[], value: number, min: number, max: number): string {
    if (max === min) {
        return range[range.length - 1]
    }
    const t = Math.max(0, Math.min(1, (value - min) / (max - min)))
    if (range.length === 2) {
        return lerpColor(range[0], range[1], t)
    }
    if (t <= 0.5) {
        return lerpColor(range[0], range[1], t * 2)
    }
    return lerpColor(range[1], range[2], (t - 0.5) * 2)
}

function lerpColor(a: string, b: string, t: number): string {
    const [ar, ag, ab] = hexToRgb(a)
    const [br, bg, bb] = hexToRgb(b)
    const r = Math.round(ar + (br - ar) * t)
    const g = Math.round(ag + (bg - ag) * t)
    const bl = Math.round(ab + (bb - ab) * t)
    return `rgb(${r}, ${g}, ${bl})`
}

function hexToRgb(hex: string): [number, number, number] {
    const clean = hex.replace('#', '')
    if (clean.length === 3) {
        return [
            parseInt(clean[0] + clean[0], 16),
            parseInt(clean[1] + clean[1], 16),
            parseInt(clean[2] + clean[2], 16),
        ]
    }
    return [parseInt(clean.slice(0, 2), 16), parseInt(clean.slice(2, 4), 16), parseInt(clean.slice(4, 6), 16)]
}

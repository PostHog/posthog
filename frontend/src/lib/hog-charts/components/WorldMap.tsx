import { useMemo } from 'react'

import type { WorldMapProps } from '../types'
import { formatValue } from '../utils/format'
import { mergeTheme } from '../utils/theme'

export function WorldMap(props: WorldMapProps): JSX.Element {
    const { data } = props
    const theme = mergeTheme(props.theme)
    const colorRange = props.colorRange ?? ['#E8E8E8', theme.colors[0]]

    const { minVal, maxVal } = useMemo(() => {
        let min = Infinity
        let max = -Infinity
        for (const d of data) {
            if (d.value < min) {
                min = d.value
            }
            if (d.value > max) {
                max = d.value
            }
        }
        return { minVal: min, maxVal: max }
    }, [data])

    const width = typeof props.width === 'number' ? props.width : 800
    const height = typeof props.height === 'number' ? props.height : 400

    const style: React.CSSProperties = {
        width: typeof props.width === 'number' ? `${props.width}px` : (props.width ?? '100%'),
        height: typeof props.height === 'number' ? `${props.height}px` : (props.height ?? 'auto'),
        fontFamily: theme.fontFamily,
        position: 'relative',
    }

    return (
        <div className={props.className} style={style} role="figure" aria-label={props.ariaLabel ?? 'World map'}>
            <svg viewBox={`0 0 ${width} ${height}`} width="100%" height="100%">
                <text x={width / 2} y={height / 2} textAnchor="middle" fill={theme.axisColor} fontSize={14}>
                    World map — {data.length} countries with data
                </text>
                <text x={width / 2} y={height / 2 + 20} textAnchor="middle" fill={theme.axisColor} fontSize={11}>
                    Range: {formatValue(minVal, 'compact')} – {formatValue(maxVal, 'compact')}
                </text>
            </svg>
            <div
                style={{
                    position: 'absolute',
                    bottom: 8,
                    right: 8,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    fontSize: (theme.fontSize ?? 12) - 2,
                    color: theme.axisColor,
                }}
            >
                <span>{formatValue(minVal, 'compact')}</span>
                <div
                    style={{
                        width: 80,
                        height: 8,
                        borderRadius: 4,
                        background: `linear-gradient(to right, ${colorRange[0]}, ${colorRange[1]})`,
                    }}
                />
                <span>{formatValue(maxVal, 'compact')}</span>
            </div>
        </div>
    )
}

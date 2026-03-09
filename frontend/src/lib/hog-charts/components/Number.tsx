import type { NumberProps } from '../types'
import { computeDelta, formatValue } from '../utils/format'
import { mergeTheme } from '../utils/theme'

export function BigNumber(props: NumberProps): JSX.Element {
    const { value, previousValue, label, format = 'compact', prefix, suffix, theme: themeOverrides } = props
    const theme = mergeTheme(themeOverrides)

    const formattedValue = formatValue(value, format, { prefix, suffix })

    let deltaEl: JSX.Element | null = null
    if (previousValue !== undefined) {
        const delta = computeDelta(value, previousValue)
        const isPositive = delta > 0
        const isZero = delta === 0
        const deltaColor = isZero ? theme.axisColor : isPositive ? '#1AA35C' : '#F04F58'
        const arrow = isZero ? '' : isPositive ? '\u2191' : '\u2193'
        const deltaText = Number.isFinite(delta) ? `${arrow} ${Math.abs(delta * 100).toFixed(1)}%` : `${arrow} \u221E`

        deltaEl = (
            <div
                style={{
                    fontSize: theme.fontSize ? theme.fontSize * 1.3 : 16,
                    fontFamily: theme.fontFamily,
                    color: deltaColor,
                    fontWeight: 600,
                    marginTop: 4,
                }}
            >
                {deltaText}
            </div>
        )
    }

    const style: React.CSSProperties = {
        width: typeof props.width === 'number' ? `${props.width}px` : (props.width ?? '100%'),
        height: typeof props.height === 'number' ? `${props.height}px` : (props.height ?? 'auto'),
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        textAlign: 'center',
    }

    return (
        <div className={props.className} style={style} role="figure" aria-label={props.ariaLabel ?? label ?? 'KPI'}>
            <div
                style={{
                    fontSize: theme.fontSize ? theme.fontSize * 4 : 48,
                    fontFamily: theme.fontFamily,
                    fontWeight: 700,
                    lineHeight: 1.1,
                    color: theme.colors[0],
                }}
            >
                {formattedValue}
            </div>
            {deltaEl}
            {label && (
                <div
                    style={{
                        fontSize: theme.fontSize ? theme.fontSize * 1.2 : 14,
                        fontFamily: theme.fontFamily,
                        color: theme.axisColor,
                        marginTop: 8,
                    }}
                >
                    {label}
                </div>
            )}
        </div>
    )
}

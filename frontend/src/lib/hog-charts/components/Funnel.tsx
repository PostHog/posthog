import type { FunnelProps, FunnelStep } from '../types'
import { formatValue } from '../utils/format'
import { mergeTheme, seriesColor } from '../utils/theme'

export function Funnel(props: FunnelProps): JSX.Element {
    const { steps, layout = 'horizontal', showConversionRates = true, showTime = false } = props
    const theme = mergeTheme(props.theme)

    if (steps.length === 0) {
        return <div className={props.className}>No funnel data</div>
    }

    const maxCount = steps[0].count
    const isHorizontal = layout === 'horizontal'

    const style: React.CSSProperties = {
        width: typeof props.width === 'number' ? `${props.width}px` : (props.width ?? '100%'),
        height: typeof props.height === 'number' ? `${props.height}px` : (props.height ?? 'auto'),
        display: 'flex',
        flexDirection: isHorizontal ? 'column' : 'row',
        gap: 2,
        fontFamily: theme.fontFamily,
        fontSize: theme.fontSize,
    }

    return (
        <div className={props.className} style={style} role="figure" aria-label={props.ariaLabel ?? 'Funnel'}>
            {steps.map((step, i) => (
                <FunnelStepRow
                    key={step.label}
                    step={step}
                    index={i}
                    maxCount={maxCount}
                    prevCount={i > 0 ? steps[i - 1].count : undefined}
                    theme={theme}
                    isHorizontal={isHorizontal}
                    showConversionRate={showConversionRates}
                    showTime={showTime}
                />
            ))}
        </div>
    )
}

function FunnelStepRow({
    step,
    index,
    maxCount,
    prevCount,
    theme,
    isHorizontal,
    showConversionRate,
    showTime,
}: {
    step: FunnelStep
    index: number
    maxCount: number
    prevCount: number | undefined
    theme: ReturnType<typeof mergeTheme>
    isHorizontal: boolean
    showConversionRate: boolean
    showTime: boolean
}): JSX.Element {
    const fillPct = maxCount > 0 ? (step.count / maxCount) * 100 : 0
    const conversionRate = prevCount && prevCount > 0 ? ((step.count / prevCount) * 100).toFixed(1) : null
    const overallRate = maxCount > 0 ? ((step.count / maxCount) * 100).toFixed(1) : null
    const color = seriesColor(theme, index)

    if (isHorizontal) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, minHeight: 40 }}>
                <div style={{ width: 120, flexShrink: 0, textAlign: 'right', color: theme.axisColor }}>
                    {step.label}
                </div>
                <div style={{ flex: 1, position: 'relative', height: 32, borderRadius: 4, overflow: 'hidden' }}>
                    <div
                        style={{
                            position: 'absolute',
                            left: 0,
                            top: 0,
                            bottom: 0,
                            width: `${fillPct}%`,
                            backgroundColor: color,
                            borderRadius: 4,
                            transition: 'width 0.3s ease',
                        }}
                    />
                    <div
                        style={{
                            position: 'relative',
                            zIndex: 1,
                            padding: '6px 10px',
                            color: fillPct > 30 ? '#fff' : theme.axisColor,
                            fontWeight: 600,
                            fontSize: theme.fontSize,
                        }}
                    >
                        {formatValue(step.count, 'compact')}
                    </div>
                </div>
                <div
                    style={{
                        width: 80,
                        flexShrink: 0,
                        textAlign: 'left',
                        color: theme.axisColor,
                        fontSize: theme.fontSize ? theme.fontSize - 1 : 11,
                    }}
                >
                    {showConversionRate && conversionRate && index > 0 ? `${conversionRate}%` : ''}
                    {showConversionRate && overallRate && index > 0 ? ` (${overallRate}%)` : ''}
                </div>
                {showTime && step.medianTime !== undefined && (
                    <div
                        style={{
                            width: 60,
                            flexShrink: 0,
                            color: theme.axisColor,
                            fontSize: theme.fontSize ? theme.fontSize - 1 : 11,
                        }}
                    >
                        {formatValue(step.medianTime, 'duration')}
                    </div>
                )}
            </div>
        )
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, gap: 4 }}>
            <div
                style={{
                    width: '100%',
                    height: `${fillPct}%`,
                    minHeight: 20,
                    backgroundColor: color,
                    borderRadius: 4,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: '#fff',
                    fontWeight: 600,
                    fontSize: theme.fontSize,
                }}
            >
                {formatValue(step.count, 'compact')}
            </div>
            <div
                style={{
                    color: theme.axisColor,
                    fontSize: theme.fontSize ? theme.fontSize - 1 : 11,
                    textAlign: 'center',
                }}
            >
                {step.label}
            </div>
            {showConversionRate && conversionRate && index > 0 && (
                <div style={{ color: theme.axisColor, fontSize: theme.fontSize ? theme.fontSize - 2 : 10 }}>
                    {conversionRate}%
                </div>
            )}
        </div>
    )
}

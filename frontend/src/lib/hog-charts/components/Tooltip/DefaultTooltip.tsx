import { formatValue } from 'lib/charts/utils/format'

import type { HogChartTheme, TooltipConfig, TooltipContext } from '../../types'
import { mergeTheme } from '../../utils/theme'

export function DefaultTooltip({
    context,
    theme: themeOverrides,
    formatValueFn,
}: {
    context: TooltipContext
    theme?: Partial<HogChartTheme>
    formatValueFn?: TooltipConfig['formatValue']
}): JSX.Element {
    const theme = mergeTheme(themeOverrides)

    return (
        <div
            className="pointer-events-none z-50 max-w-80 rounded px-3 py-2 shadow-lg"
            style={{
                backgroundColor: theme.tooltipBackground,
                color: theme.tooltipColor,
                borderRadius: theme.tooltipBorderRadius,
                fontFamily: theme.fontFamily,
                fontSize: theme.fontSize,
            }}
        >
            {context.label && (
                <div
                    className="font-semibold opacity-70"
                    style={{
                        marginBottom: context.points.length > 0 ? 6 : 0,
                        fontSize: (theme.fontSize ?? 12) - 1,
                    }}
                >
                    {context.label}
                </div>
            )}
            {context.points.map((point) => (
                <div key={`${point.seriesIndex}-${point.pointIndex}`} className="flex items-center gap-2 py-0.5">
                    <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: point.color }} />
                    <span className="flex-1 truncate">{point.seriesLabel}</span>
                    <span className="ml-3 font-semibold tabular-nums">
                        {formatValueFn
                            ? formatValueFn(point.value, point.seriesIndex)
                            : formatValue(point.value, 'compact')}
                    </span>
                </div>
            ))}
        </div>
    )
}

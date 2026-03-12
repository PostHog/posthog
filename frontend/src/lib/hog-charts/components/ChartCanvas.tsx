import type { ChartConfiguration, ChartType } from 'chart.js'

import { useHogChart } from '../hooks'
import type { BaseChartProps } from '../types'
import { TooltipPortal, useTooltipState } from './tooltip'

export function ChartCanvas<TType extends ChartType = ChartType>({
    config,
    width = '100%',
    height = 300,
    className,
    ariaLabel,
    ...chartProps
}: {
    config: ChartConfiguration<TType> | null
} & BaseChartProps): JSX.Element {
    const { tooltipContext, showTooltip, hideTooltip } = useTooltipState()

    const tooltipCallbacks = chartProps.tooltip ? { onShow: showTooltip, onHide: hideTooltip } : undefined

    const { canvasRef, containerRef } = useHogChart(config, chartProps, tooltipCallbacks)

    return (
        <div
            ref={containerRef}
            className={`relative w-full grow overflow-hidden ${className ?? ''}`}
            style={{
                width: typeof width === 'number' ? `${width}px` : width,
                height: typeof height === 'number' ? `${height}px` : height,
            }}
        >
            <canvas ref={canvasRef} role="img" aria-label={ariaLabel ?? 'Chart'} />
            {chartProps.tooltip && (
                <TooltipPortal
                    context={tooltipContext}
                    config={chartProps.tooltip}
                    theme={chartProps.theme}
                    containerRef={containerRef}
                />
            )}
        </div>
    )
}

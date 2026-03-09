import type { ChartConfiguration, ChartType } from 'chart.js'
import type React from 'react'

import { useHogChart } from '../hooks'
import type { BaseChartProps } from '../types'
import { TooltipPortal, useTooltipState } from './Tooltip'

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

    const tooltipCallbacks = chartProps.tooltip?.render ? { onShow: showTooltip, onHide: hideTooltip } : undefined

    const { canvasRef, containerRef } = useHogChart(config, chartProps, tooltipCallbacks)

    const style: React.CSSProperties = {
        width: typeof width === 'number' ? `${width}px` : width,
        height: typeof height === 'number' ? `${height}px` : height,
        position: 'relative',
    }

    return (
        <div ref={containerRef} className={className} style={style}>
            <canvas ref={canvasRef} role="img" aria-label={ariaLabel ?? 'Chart'} />
            {chartProps.tooltip?.render && (
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

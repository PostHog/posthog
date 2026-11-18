import { CSSProperties } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

export type BIChartAxis = 'x' | 'left' | 'right'

export function BIChartAxisControls({ onEdit }: { onEdit: (axis: BIChartAxis) => void }): JSX.Element {
    const { dimensions, axis, yGutters } = useChartLayout()
    const { plotLeft, plotTop, plotWidth, plotHeight, width, height } = dimensions
    const horizontal = axis.orientation === 'horizontal'
    const targets: { axis: BIChartAxis; label: string; style: CSSProperties }[] = [
        {
            axis: horizontal ? 'left' : 'x',
            label: 'Edit bottom axis',
            style: {
                left: plotLeft,
                top: plotTop + plotHeight,
                width: plotWidth,
                height: height - plotTop - plotHeight,
            },
        },
        {
            axis: horizontal ? 'x' : 'left',
            label: 'Edit left axis',
            style: { left: 0, top: plotTop, width: plotLeft, height: plotHeight },
        },
        ...(!horizontal && yGutters.some((gutter) => gutter.side === 'right')
            ? [
                  {
                      axis: 'right' as const,
                      label: 'Edit right axis',
                      style: {
                          left: plotLeft + plotWidth,
                          top: plotTop,
                          width: width - plotLeft - plotWidth,
                          height: plotHeight,
                      },
                  },
              ]
            : []),
    ]
    return (
        <>
            {targets.map((target) => (
                <button
                    key={target.axis}
                    type="button"
                    className="pointer-events-auto absolute cursor-pointer rounded border border-transparent bg-transparent hover:border-primary focus-visible:border-primary focus-visible:outline-none"
                    // Axis hit areas follow the chart's measured gutters, including horizontal bars.
                    // eslint-disable-next-line react/forbid-dom-props
                    style={target.style}
                    aria-label={target.label}
                    title={target.label}
                    onClick={() => onEdit(target.axis)}
                />
            ))}
        </>
    )
}

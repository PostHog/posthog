import { useSvgResizeObserver } from '../hooks/useSvgResizeObserver'
import { TickPanel } from '../TickPanel'
import { valueToXCoordinate } from '../utils'

export function ConfidenceIntervalAxis(): JSX.Element {
    const tickValues = [-0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3]
    const chartBound = 0.30445147785257376
    const viewBoxWidth = 800
    const horizontalPadding = 20
    const tickPanelHeight = 20
    const valueToX = (value: number): number => valueToXCoordinate(value, chartBound, viewBoxWidth, horizontalPadding)

    const { ticksSvgRef, ticksSvgHeight } = useSvgResizeObserver([tickValues, chartBound])
    return (
        <div className="flex border-t border-l border-r rounded-t">
            <div className="w-1/5 border-r border-primary">
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ height: `${ticksSvgHeight}px` }}
                />
            </div>
            <div className="w-4/5 min-w-[780px]">
                <div className="flex justify-center">
                    <TickPanel
                        svgRef={ticksSvgRef}
                        tickValues={tickValues}
                        valueToX={valueToX}
                        viewBoxWidth={viewBoxWidth}
                        tickPanelHeight={tickPanelHeight}
                    />
                </div>
            </div>
        </div>
    )
}

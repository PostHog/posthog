import { getNiceTickValues } from '../shared/utils'
import { useAxisScale } from './useAxisScale'
import { GridLines } from './GridLines'
import { TickLabels } from './TickLabels'

interface ChartAxisProps {
    chartRadius: number
    height: number
    viewBoxWidth?: number
    edgeMargin?: number
    showGridLines?: boolean
    showTickLabels?: boolean
    tickLabelsY?: number
    gridLinesProps?: Partial<React.ComponentProps<typeof GridLines>>
    tickLabelsProps?: Partial<React.ComponentProps<typeof TickLabels>>
}

/**
 * Combined component that renders both grid lines and tick labels for experiment charts.
 * Provides a simple API for common axis rendering needs.
 */
export function ChartAxis({
    chartRadius,
    height,
    viewBoxWidth = 800,
    edgeMargin = 20,
    showGridLines = true,
    showTickLabels = true,
    tickLabelsY = 10,
    gridLinesProps = {},
    tickLabelsProps = {},
}: ChartAxisProps): JSX.Element {
    const tickValues = getNiceTickValues(chartRadius)
    const scale = useAxisScale(chartRadius, viewBoxWidth, edgeMargin)

    return (
        <>
            {showGridLines && (
                <GridLines
                    tickValues={tickValues}
                    scale={scale}
                    height={height}
                    viewBoxWidth={viewBoxWidth}
                    {...gridLinesProps}
                />
            )}
            {showTickLabels && (
                <TickLabels
                    tickValues={tickValues}
                    scale={scale}
                    y={tickLabelsY}
                    viewBoxWidth={viewBoxWidth}
                    {...tickLabelsProps}
                />
            )}
        </>
    )
}

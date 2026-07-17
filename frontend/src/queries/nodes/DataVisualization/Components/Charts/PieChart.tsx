import { ChartSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'
import { SqlPieGraph } from './SqlPieGraph'

export interface PieChartProps {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[]
    chartSettings: ChartSettings
    presetChartHeight?: boolean
    className?: string
}

export function PieChart(props: PieChartProps): JSX.Element {
    const sqlPieProps: LineGraphProps = {
        xData: props.xData,
        yData: props.yData,
        visualizationType: ChartDisplayType.ActionsPie,
        chartSettings: props.chartSettings,
        presetChartHeight: props.presetChartHeight,
        className: props.className,
    }

    return <SqlPieGraph {...sqlPieProps} />
}

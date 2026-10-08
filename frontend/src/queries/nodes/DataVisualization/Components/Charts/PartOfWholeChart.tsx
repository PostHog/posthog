import { ChartSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { SqlPieGraph } from './SqlPieGraph'
import { SqlProportionBar } from './SqlProportionBar'

export interface PartOfWholeChartProps {
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[] | AxisBreakdownSeries<number | null>[]
    visualizationType: ChartDisplayType
    chartSettings: ChartSettings
    presetChartHeight?: boolean
    className?: string
}

export function PartOfWholeChart(props: PartOfWholeChartProps): JSX.Element {
    return props.visualizationType === ChartDisplayType.ActionsProportionBar ? (
        <SqlProportionBar {...props} />
    ) : (
        <SqlPieGraph {...props} />
    )
}

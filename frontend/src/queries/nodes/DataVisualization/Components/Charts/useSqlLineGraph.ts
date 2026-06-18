import { type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { LineGraphProps } from './LineGraph'
import { buildLineChartConfig } from './sqlLineGraphAdapter'
import { type SqlChartModel, useSqlChartModel } from './useSqlChartModel'

export type SqlLineGraphModel = SqlChartModel<TimeSeriesLineChartConfig>

export function useSqlLineGraph(props: LineGraphProps): SqlLineGraphModel | null {
    return useSqlChartModel(props, buildLineChartConfig)
}

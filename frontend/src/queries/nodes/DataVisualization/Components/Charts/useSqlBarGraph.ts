import { type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { LineGraphProps } from './LineGraph'
import { buildBarChartConfig } from './sqlLineGraphAdapter'
import { type SqlChartModel, useSqlChartModel } from './useSqlChartModel'

export type SqlBarGraphModel = SqlChartModel<TimeSeriesBarChartConfig>

export function useSqlBarGraph(props: LineGraphProps): SqlBarGraphModel | null {
    return useSqlChartModel(props, buildBarChartConfig)
}

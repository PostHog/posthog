import { actions, kea, key, path, props, reducers } from 'kea'

import type { flintQuillVisualizationLogicType } from './flintQuillVisualizationLogicType'

export interface FlintQuillVisualizationLogicProps {
    key: string
}

export const flintQuillVisualizationLogic = kea<flintQuillVisualizationLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'Charts', 'flintQuillVisualizationLogic']),
    props({} as FlintQuillVisualizationLogicProps),
    key((props) => props.key),
    actions({
        setChartType: (chartType: string | null) => ({ chartType }),
    }),
    reducers({
        // null = infer the chart type from the result shape
        chartType: [
            null as string | null,
            {
                setChartType: (_, { chartType }) => chartType,
            },
        ],
    }),
])

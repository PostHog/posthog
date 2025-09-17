import { SpinnerOverlay } from '@posthog/lemon-ui'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType } from '~/types'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'

export function AppMetricsTrends({
    appMetricsTrends,
    loading,
}: {
    appMetricsTrends: AppMetricsTimeSeriesResponse | null
    loading: boolean
}): JSX.Element {
    return (
        <div className="relative border rounded min-h-[20rem] h-[70vh] bg-white">
            {loading ? (
                <SpinnerOverlay />
            ) : !appMetricsTrends ? (
                <div className="flex-1 flex items-center justify-center">Missing</div>
            ) : (
                <LineGraph
                    className="p-2"
                    xData={{
                        column: {
                            name: 'date',
                            type: {
                                name: 'DATE',
                                isNumerical: false,
                            },
                            label: 'Date',
                            dataIndex: 0,
                        },
                        data: appMetricsTrends.labels,
                    }}
                    yData={appMetricsTrends.series.map((x) => ({
                        column: {
                            name: x.name,
                            type: { name: 'INTEGER', isNumerical: true },
                            label: x.name,
                            dataIndex: 0,
                        },
                        data: x.values,
                    }))}
                    visualizationType={ChartDisplayType.ActionsLineGraph}
                    chartSettings={{
                        showLegend: true,
                        showTotalRow: false,
                    }}
                />
            )}
        </div>
    )
}

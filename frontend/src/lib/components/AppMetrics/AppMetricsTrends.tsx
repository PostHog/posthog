import { SpinnerOverlay } from '@posthog/lemon-ui'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType } from '~/types'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'

export function AppMetricsTrends({
    appMetricsTrends,
    loading,
    metricLabels,
}: {
    appMetricsTrends: AppMetricsTimeSeriesResponse | null
    loading: boolean
    /** Optional display labels keyed by series name (e.g. `{ rows_synced: 'Rows synced' }`). */
    metricLabels?: Record<string, string>
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
                    yData={appMetricsTrends.series.map((x) => {
                        const label = metricLabels?.[x.name] ?? x.name
                        return {
                            column: {
                                name: label,
                                type: { name: 'INTEGER', isNumerical: true },
                                label,
                                dataIndex: 0,
                            },
                            data: x.values,
                        }
                    })}
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

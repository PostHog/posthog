import { useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { appMetricsLogic, AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType } from '~/types'

const EVENT_FILTER_METRIC_KEYS = ['dropped', 'would_be_dropped'] as const

function CompactMetricsChart({
    data,
    loading,
}: {
    data: AppMetricsTimeSeriesResponse | null
    loading: boolean
}): JSX.Element {
    return (
        <div className="relative border rounded h-52">
            {loading ? (
                <SpinnerOverlay />
            ) : !data ? (
                <div className="flex-1 flex items-center justify-center text-muted text-sm">No data</div>
            ) : (
                <LineGraph
                    className="p-2"
                    xData={{
                        column: {
                            name: 'date',
                            type: { name: 'DATE', isNumerical: false },
                            label: 'Date',
                            dataIndex: 0,
                        },
                        data: data.labels,
                    }}
                    yData={data.series.map((x) => ({
                        column: {
                            name: x.name,
                            type: { name: 'INTEGER', isNumerical: true },
                            label: x.name,
                            dataIndex: 0,
                        },
                        data: x.values,
                    }))}
                    visualizationType={ChartDisplayType.ActionsLineGraph}
                    chartSettings={{ showLegend: true, showTotalRow: false }}
                />
            )}
        </div>
    )
}

export function EventFilterMetrics({ filterId }: { filterId: string | null }): JSX.Element | null {
    const logicKey = `event-filter-metrics-${filterId ?? 'none'}`

    const logic = filterId
        ? appMetricsLogic({
              logicKey,
              loadOnMount: true,
              loadOnChanges: true,
              forceParams: {
                  appSource: 'event_filter',
                  appSourceId: filterId,
                  metricName: [...EVENT_FILTER_METRIC_KEYS],
                  breakdownBy: 'metric_name',
              },
          })
        : null

    const { appMetricsTrends, appMetricsTrendsLoading } = useValues(logic ?? appMetricsLogic({ logicKey: 'noop' }))

    if (!filterId) {
        return null
    }

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <label className="font-semibold">Metrics</label>
                <AppMetricsFilters logicKey={logicKey} />
            </div>
            <CompactMetricsChart data={appMetricsTrends} loading={appMetricsTrendsLoading} />
            <p className="text-muted text-xs">
                These counts are approximate. The actual number of dropped events may differ by a small percentage.
            </p>
        </div>
    )
}

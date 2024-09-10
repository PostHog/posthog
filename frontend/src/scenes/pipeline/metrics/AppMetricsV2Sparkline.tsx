import { useActions, useValues } from 'kea'
import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { useEffect } from 'react'

import { appMetricsV2Logic, AppMetricsV2LogicProps } from './appMetricsV2Logic'

export function AppMetricSparkLineV2({ id }: AppMetricsV2LogicProps): JSX.Element {
    const logic = appMetricsV2Logic({ id })
    const { appMetrics, appMetricsLoading } = useValues(logic)
    const { loadMetrics } = useActions(logic)

    useEffect(() => {
        loadMetrics()
    }, [])

    const displayData: SparklineTimeSeries[] = [
        {
            color: 'success',
            name: 'Success',
            values: appMetrics?.series.find((s) => s.name === 'succeeded')?.values || [],
        },
        {
            color: 'danger',
            name: 'Failures',
            values: appMetrics?.series.find((s) => s.name === 'failed')?.values || [],
        },
    ]

    return (
        <Sparkline
            loading={appMetricsLoading}
            labels={appMetrics?.labels}
            data={displayData}
            className="max-w-24 h-8"
            maximumIndicator={false}
        />
    )
}

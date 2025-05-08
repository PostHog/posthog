import { LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { useEffect } from 'react'

import { hogFunctionMetricsLogic, HogFunctionMetricsLogicProps } from './hogFunctionMetricsLogic'

export function HogFunctionMetricSparkLine({ id }: HogFunctionMetricsLogicProps): JSX.Element {
    const logic = hogFunctionMetricsLogic({ id })
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

    return !appMetrics || appMetricsLoading ? (
        <LemonSkeleton className="h-8 max-w-24" />
    ) : (
        <Sparkline
            loading={appMetricsLoading}
            labels={appMetrics?.labels}
            data={displayData}
            className="h-8 max-w-24"
            maximumIndicator={false}
        />
    )
}

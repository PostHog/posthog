import { LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { inStorybookTestRunner } from 'lib/utils'
import { useEffect } from 'react'
import { useInView } from 'react-intersection-observer'

import { hogFunctionMetricsLogic, HogFunctionMetricsLogicProps } from './hogFunctionMetricsLogic'

export function HogFunctionMetricSparkLine({ id }: HogFunctionMetricsLogicProps): JSX.Element {
    const logic = hogFunctionMetricsLogic({ id })
    const { appMetrics, appMetricsLoading } = useValues(logic)
    const { loadMetrics } = useActions(logic)
    const { ref: inViewRef, inView } = useInView()

    useEffect(() => {
        if (inStorybookTestRunner() || (inView && !appMetrics && !appMetricsLoading)) {
            loadMetrics()
        }
    }, [inView])

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
        <div ref={inViewRef}>
            {!inView || !appMetrics || appMetricsLoading ? (
                <LemonSkeleton className="h-8 max-w-24" />
            ) : (
                <Sparkline
                    labels={appMetrics.labels}
                    data={displayData}
                    className="h-8 max-w-24"
                    maximumIndicator={false}
                />
            )}
        </div>
    )
}

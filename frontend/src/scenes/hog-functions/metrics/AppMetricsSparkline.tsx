import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { useInView } from 'react-intersection-observer'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { inStorybookTestRunner } from 'lib/utils'

import { AppMetricsLogicProps, appMetricsLogic } from './appMetricsLogic'

export function AppMetricsSparkline(props: AppMetricsLogicProps): JSX.Element {
    const logic = appMetricsLogic(props)
    const { appMetricsTrends, appMetricsTrendsLoading } = useValues(logic)
    const { loadAppMetricsTrends } = useActions(logic)
    const { ref: inViewRef, inView } = useInView()

    useEffect(() => {
        if (inStorybookTestRunner() || (inView && !appMetricsTrends && !appMetricsTrendsLoading)) {
            loadAppMetricsTrends()
        }
    }, [inView]) // oxlint-disable-line react-hooks/exhaustive-deps

    const displayData: SparklineTimeSeries[] =
        appMetricsTrends?.series.map((s) => ({
            color: s.name === 'success' ? 'success' : 'danger',
            name: s.name,
            values: s.values,
        })) || []

    const labels = appMetricsTrends?.labels || []

    return (
        <div ref={inViewRef}>
            {!inView || !appMetricsTrends || appMetricsTrendsLoading ? (
                <LemonSkeleton className="h-8 max-w-24" />
            ) : (
                <Sparkline labels={labels} data={displayData} className="h-8 max-w-24" maximumIndicator={false} />
            )}
        </div>
    )
}

import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'
import { useInView } from 'react-intersection-observer'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { inStorybookTestRunner } from 'lib/utils'

import { AppMetricsLogicProps, appMetricsLogic } from './appMetricsLogic'

export function AppMetricsSparkline(props: AppMetricsLogicProps): JSX.Element {
    const logic = appMetricsLogic(props)
    const { appMetricsTrends, appMetricsTrendsLoading, params } = useValues(logic)
    const { loadAppMetricsTrends } = useActions(logic)
    const { ref: inViewRef, inView } = useInView({
        triggerOnce: true,
    })

    useEffect(() => {
        if (inStorybookTestRunner() || (inView && !appMetricsTrendsLoading)) {
            loadAppMetricsTrends()
        }
    }, [inView]) // oxlint-disable-line react-hooks/exhaustive-deps

    const displayData: SparklineTimeSeries[] = useMemo(() => {
        // We sort the series based on the given metricKind

        const sortListValue = params.breakdownBy === 'metric_kind' ? params.metricKind : params.metricName
        const sortList = sortListValue ? (Array.isArray(sortListValue) ? sortListValue : [sortListValue]) : []

        const sortedSeries =
            sortList.length > 0
                ? appMetricsTrends?.series.sort((a, b) => {
                      return sortList.indexOf(a.name) - sortList.indexOf(b.name)
                  })
                : appMetricsTrends?.series

        return (
            sortedSeries?.map((s) => ({
                color: s.name === 'success' ? 'success' : 'danger',
                name: s.name,
                values: s.values,
            })) || []
        )
    }, [appMetricsTrends, params])

    const labels = appMetricsTrends?.labels || []

    return (
        <div ref={inViewRef}>
            {!inView ? (
                <div className="h-8 max-w-24" />
            ) : !appMetricsTrends || appMetricsTrendsLoading ? (
                <LemonSkeleton className="h-8 max-w-24" />
            ) : (
                <Sparkline labels={labels} data={displayData} className="h-8 max-w-24" maximumIndicator={false} />
            )}
        </div>
    )
}

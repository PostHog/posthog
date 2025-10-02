import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'
import { useInView } from 'react-intersection-observer'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { inStorybookTestRunner } from 'lib/utils'

import { AppMetricsLogicProps, appMetricsLogic } from './appMetricsLogic'

export function AppMetricsSparkline(props: AppMetricsLogicProps): JSX.Element {
    // Disable automatic loading on prop changes to control loading manually
    const logic = appMetricsLogic({ ...props, loadOnChanges: false })
    const { appMetricsTrends, appMetricsTrendsLoading, params } = useValues(logic)
    const { loadAppMetricsTrends } = useActions(logic)

    const hasLoadedRef = useRef(false)
    const { ref: inViewRef, inView } = useInView({
        threshold: 0.1, // Lower threshold to start loading a bit earlier
        triggerOnce: true,
        rootMargin: '100px', // Start loading 100px before visible for smoother UX
    })

    useEffect(() => {
        if ((inStorybookTestRunner() || inView) && !hasLoadedRef.current && !appMetricsTrendsLoading) {
            hasLoadedRef.current = true
            loadAppMetricsTrends()
        }
    }, [inView, appMetricsTrendsLoading, loadAppMetricsTrends])

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
            {!inView && !appMetricsTrends ? (
                <div className="h-8 max-w-24" />
            ) : !appMetricsTrends || appMetricsTrendsLoading ? (
                <LemonSkeleton className="h-8 max-w-24" />
            ) : (
                <Sparkline labels={labels} data={displayData} className="h-8 max-w-24" maximumIndicator={false} />
            )}
        </div>
    )
}

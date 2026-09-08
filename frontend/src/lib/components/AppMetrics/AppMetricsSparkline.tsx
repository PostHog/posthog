import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'
import { useInView } from 'react-intersection-observer'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { inStorybookTestRunner } from 'lib/utils/dom'

import { AppMetricsLogicProps, appMetricsLogic } from './appMetricsLogic'

export interface AppMetricsSparklineProps extends AppMetricsLogicProps {
    /** Series names to render in the success color. Defaults to `['success']`. */
    successMetricNames?: string[]
    /** Optional display labels keyed by series name (e.g. `{ rows_synced: 'Rows synced' }`). */
    metricLabels?: Record<string, string>
    /** Optional vars.scss color names keyed by series name; takes precedence over `successMetricNames`. */
    metricColors?: Record<string, string>
    /** Bars stack their series. Pass `'line'` when series overlap and a summed height would mislead. @default 'bar' */
    type?: 'bar' | 'line'
}

const DEFAULT_SUCCESS_METRIC_NAMES = ['success']

export function AppMetricsSparkline({
    successMetricNames,
    metricLabels,
    metricColors,
    type,
    ...props
}: AppMetricsSparklineProps): JSX.Element {
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
        const successNames = successMetricNames ?? DEFAULT_SUCCESS_METRIC_NAMES

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
                color: metricColors?.[s.name] ?? (successNames.includes(s.name) ? 'success' : 'danger'),
                name: metricLabels?.[s.name] ?? s.name,
                values: s.values,
            })) || []
        )
    }, [appMetricsTrends, params, successMetricNames, metricLabels, metricColors])

    const labels = appMetricsTrends?.labels || []

    return (
        <div ref={inViewRef}>
            {!inView ? (
                <div className="h-8 max-w-24" />
            ) : !appMetricsTrends || appMetricsTrendsLoading ? (
                <LemonSkeleton className="h-8 max-w-24" />
            ) : (
                <Sparkline labels={labels} data={displayData} type={type} className="h-8 max-w-24" />
            )}
        </div>
    )
}

import { useActions, useValues } from 'kea'
import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { useEffect } from 'react'
import { useInView } from 'react-intersection-observer'

import { pipelineNodeMetricsLogic } from './pipelineNodeMetricsLogic'
import { PipelineNode } from './types'

export function AppMetricSparkLine({ pipelineNode }: { pipelineNode: PipelineNode }): JSX.Element {
    const logic = pipelineNodeMetricsLogic({ id: pipelineNode.id })
    const { appMetricsResponse, appMetricsResponseLoading } = useValues(logic)
    const { loadMetrics } = useActions(logic)
    const { ref: inViewRef, inView } = useInView()

    useEffect(() => {
        if (inView && !appMetricsResponse && !appMetricsResponseLoading) {
            loadMetrics()
        }
    }, [inView])

    // The metrics response has last 7 days time wise, we're showing the
    // sparkline graph by day, so ignore the potential 8th day
    const successes = appMetricsResponse ? appMetricsResponse.metrics.successes.slice(-7) : []
    const failures = appMetricsResponse ? appMetricsResponse.metrics.failures.slice(-7) : []
    const dates = appMetricsResponse ? appMetricsResponse.metrics.dates.slice(-7) : []

    const displayData: SparklineTimeSeries[] = [
        {
            color: 'success',
            name: 'Success',
            values: successes,
        },
    ]

    if (appMetricsResponse?.metrics.failures.some((failure) => failure > 0)) {
        displayData.push({
            color: 'danger',
            name: 'Failure',
            values: failures,
        })
    }

    return (
        <div ref={inViewRef}>
            <Sparkline
                loading={appMetricsResponse === null}
                labels={dates}
                data={displayData}
                className="h-8 max-w-24"
                maximumIndicator={false}
            />
        </div>
    )
}

import { useActions, useValues } from 'kea'
import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { useEffect } from 'react'

import { pipelineNodeMetricsLogic } from './pipelineNodeMetricsLogic'
import { pipelineNodeMetricsV2Logic } from './pipelineNodeMetricsV2Logic'
import { PipelineNode } from './types'

export function AppMetricSparkLine({ pipelineNode }: { pipelineNode: PipelineNode }): JSX.Element {
    const logic = pipelineNodeMetricsLogic({ id: pipelineNode.id })
    const { appMetricsResponse } = useValues(logic)

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
        <Sparkline
            loading={appMetricsResponse === null}
            labels={dates}
            data={displayData}
            className="max-w-24 h-8"
            maximumIndicator={false}
        />
    )
}

export function AppMetricSparkLineV2({ pipelineNode }: { pipelineNode: PipelineNode }): JSX.Element {
    const logic = pipelineNodeMetricsV2Logic({ id: `${pipelineNode.id}`.replace('hog-', '') })
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

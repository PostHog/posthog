import { useValues } from 'kea'
import { Sparkline, SparklineTimeSeries } from 'lib/lemon-ui/Sparkline'

import { pipelineNodeMetricsLogic } from './pipelineNodeMetricsLogic'
import { PipelineBackend, PipelineNode } from './types'

export function AppMetricSparkLine({ pipelineNode }: { pipelineNode: PipelineNode }): JSX.Element {
    if (pipelineNode.backend === PipelineBackend.BatchExport) {
        return <></> // TODO: not ready yet
    } else {
        const logic = pipelineNodeMetricsLogic({ pluginConfigId: pipelineNode.id })
        const { appMetricsResponse } = useValues(logic)

        // The metrics response has last 7 days time wise, we're showing the
        // sparkline graph by day, so ignore the potential 8th day
        const successes = appMetricsResponse ? appMetricsResponse.metrics.successes.slice(-7) : []
        const failures = appMetricsResponse ? appMetricsResponse.metrics.failures.slice(-7) : []
        const dates = appMetricsResponse ? appMetricsResponse.metrics.dates.slice(-7) : []

        const displayData: SparklineTimeSeries[] = [
            {
                color: 'success',
                name: 'Events sent',
                values: successes,
            },
        ]
        if (appMetricsResponse?.metrics.failures.some((failure) => failure > 0)) {
            displayData.push({
                color: 'danger',
                name: 'Events dropped',
                values: failures,
            })
        }

        return (
            <Sparkline loading={appMetricsResponse === null} labels={dates} data={displayData} className="max-w-24" />
        )
    }
}

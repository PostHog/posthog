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

        const displayData: SparklineTimeSeries[] = [
            {
                color: 'success',
                name: 'Events sent',
                values: appMetricsResponse ? appMetricsResponse.metrics.successes : [],
            },
        ]
        if (appMetricsResponse?.metrics.failures.some((failure) => failure > 0)) {
            displayData.push({
                color: 'danger',
                name: 'Events dropped',
                values: appMetricsResponse ? appMetricsResponse.metrics.failures : [],
            })
        }

        return (
            <Sparkline
                loading={appMetricsResponse === null}
                labels={appMetricsResponse ? appMetricsResponse.metrics.dates : []}
                data={displayData}
                className="max-w-24"
            />
        )
    }
}

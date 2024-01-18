import { useValues } from 'kea'
import { Sparkline, SparklineTimeSeries } from 'lib/lemon-ui/Sparkline'

import { DestinationType, PipelineAppBackend } from './destinationsLogic'
import { pipelineAppMetricsLogic } from './pipelineAppMetricsLogic'

export function DestinationSparkLine({ destination }: { destination: DestinationType }): JSX.Element {
    if (destination.backend === PipelineAppBackend.BatchExport) {
        return <></> // TODO: not ready yet
    } else {
        const logic = pipelineAppMetricsLogic({ pluginConfigId: destination.id })
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
            />
        )
    }
}

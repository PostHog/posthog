import { LemonCollapse } from '@posthog/lemon-ui'
import { useValues } from 'kea'

import { LoadingState } from './Experiment'
import { experimentLogic } from './experimentLogic'
import { ExperimentResult } from './ExperimentResult'

export function SecondaryMetricsResult(): JSX.Element {
    // TODO: Use secondaryMetricsLogic here to add edit functionality

    const { secondaryMetricResultsLoading, experiment } = useValues(experimentLogic)

    const secondaryMetricsExist = (experiment.secondary_metrics?.length || 0) > 0

    if (!secondaryMetricsExist) {
        return <></>
    }

    return (
        <div className="mt-4">
            <h2 className="font-semibold text-lg m-0">Secondary metrics</h2>
            {secondaryMetricResultsLoading ? (
                <LoadingState />
            ) : (
                <LemonCollapse
                    className="w-full mt-4 bg-bg-light"
                    defaultActiveKey="secondary-metric-results-0"
                    panels={
                        experiment.secondary_metrics?.map((metric, index) => {
                            return {
                                key: `secondary-metric-results-${index}`,
                                header: metric.name || `Metric ${index + 1}`,
                                content: <ExperimentResult secondaryMetricId={index} />,
                            }
                        }) || []
                    }
                />
            )}
        </div>
    )
}

import { LemonInput, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { Query } from '~/queries/Query/Query'
import { ExperimentMetric, NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { filterToMetricConfig, metricConfigToFilter, metricToQuery } from '../utils'
import { commonActionFilterProps } from './Selectors'

export function ExperimentMetricForm({ isSecondary = false }: { isSecondary?: boolean }): JSX.Element {
    const { experiment, editingPrimaryMetricIndex, editingSecondaryMetricIndex } = useValues(experimentLogic)
    const { setMetric } = useActions(experimentLogic)

    const metrics = isSecondary ? experiment.metrics_secondary : experiment.metrics
    const metricIdx = isSecondary ? editingSecondaryMetricIndex : editingPrimaryMetricIndex

    if (!metricIdx && metricIdx !== 0) {
        return <></>
    }

    // TODO: We have to verify that all metrics are of type ExperimentMetric
    // before we hit any new code paths.
    const currentMetric = metrics[metricIdx] as ExperimentMetric

    return (
        <div className="space-y-4">
            <div>
                <LemonLabel>Name (optional)</LemonLabel>
                <LemonInput
                    value={currentMetric.name}
                    onChange={(newName) => {
                        setMetric({
                            metricIdx,
                            metric: {
                                ...currentMetric,
                                name: newName,
                            },
                            isSecondary,
                        })
                    }}
                />
            </div>
            <ActionFilter
                bordered
                filters={metricConfigToFilter(currentMetric.metric_config)}
                setFilters={({ actions, events }: Partial<FilterType>): void => {
                    // We only support one event/action for experiment metrics
                    const entity = events?.[0] || actions?.[0]
                    const metricConfig = filterToMetricConfig(entity)
                    if (metricConfig) {
                        setMetric({
                            metricIdx,
                            metric: {
                                ...currentMetric,
                                metric_config: metricConfig,
                            },
                            isSecondary,
                        })
                    }
                }}
                typeKey="experiment-metric"
                buttonCopy="Add graph series"
                showSeriesIndicator={false}
                hideRename={true}
                entitiesLimit={1}
                showNumericalPropsOnly={true}
                mathAvailability={MathAvailability.All}
                {...commonActionFilterProps}
            />
            <Query
                query={{
                    kind: NodeKind.InsightVizNode,
                    source: metricToQuery(currentMetric),
                    showTable: false,
                    showLastComputation: true,
                    showLastComputationRefresh: false,
                }}
                readOnly
            />
        </div>
    )
}

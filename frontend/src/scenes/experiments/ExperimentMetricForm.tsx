import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { Query } from '~/queries/Query/Query'
import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { commonActionFilterProps } from './Metrics/Selectors'
import { filterToMetricConfig, metricConfigToFilter, metricToQuery } from './utils'

export function ExperimentMetricForm({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMetric
    handleSetMetric: any
}): JSX.Element {
    return (
        <div className="space-y-4">
            <div>
                <h4 className="mb-2">Metric type</h4>
                <LemonRadio
                    data-attr="metrics-selector"
                    value={metric.metric_type}
                    onChange={(newMetricType: ExperimentMetricType) => {
                        handleSetMetric({
                            newMetric: {
                                ...metric,
                                metric_type: newMetricType,
                            },
                        })
                    }}
                    options={[
                        {
                            value: ExperimentMetricType.COUNT,
                            label: 'Count',
                            description:
                                'Tracks how many times an event happens, useful for click counts or page views.',
                        },
                        {
                            value: ExperimentMetricType.CONTINUOUS,
                            label: 'Continuous',
                            description: 'Measures numerical values like revenue or session length.',
                        },
                    ]}
                />
            </div>
            <ActionFilter
                bordered
                filters={metricConfigToFilter(metric.metric_config)}
                setFilters={({ actions, events }: Partial<FilterType>): void => {
                    // We only support one event/action for experiment metrics
                    const entity = events?.[0] || actions?.[0]
                    const metricConfig = filterToMetricConfig(entity)
                    if (metricConfig) {
                        handleSetMetric({
                            newMetric: {
                                ...metric,
                                metric_config: metricConfig,
                            },
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
                    source: metricToQuery(metric),
                    showTable: false,
                    showLastComputation: true,
                    showLastComputationRefresh: false,
                }}
                readOnly
            />
        </div>
    )
}

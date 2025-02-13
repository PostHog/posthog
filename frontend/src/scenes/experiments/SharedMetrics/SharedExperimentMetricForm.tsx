import { useActions, useValues } from 'kea'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { ActionsNode, EventsNode, ExperimentMetricType } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { commonActionFilterProps } from '../Metrics/Selectors'
import { filterToMetricConfig, metricConfigToFilter } from '../utils'
import { sharedMetricLogic } from './sharedMetricLogic'

export function SharedExperimentMetricForm(): JSX.Element {
    const { sharedMetric } = useValues(sharedMetricLogic)
    const { setSharedMetric } = useActions(sharedMetricLogic)

    if (!sharedMetric?.query) {
        return <></>
    }

    return (
        <>
            <div className="mb-4">
                <h4 className="mb-2">Metric type</h4>
                <LemonRadio
                    data-attr="metrics-selector"
                    value={sharedMetric.query.metric_type}
                    onChange={(newMetricType: ExperimentMetricType) => {
                        setSharedMetric({
                            ...sharedMetric,
                            query: {
                                ...sharedMetric.query,
                                metric_type: newMetricType,
                            },
                        })
                    }}
                    options={[
                        { value: ExperimentMetricType.COUNT, label: 'Count' },
                        { value: ExperimentMetricType.CONTINUOUS, label: 'Continuous' },
                    ]}
                />
            </div>
            <ActionFilter
                bordered
                filters={metricConfigToFilter(sharedMetric.query.metric_config)}
                setFilters={({ actions, events }: Partial<FilterType>): void => {
                    // We only support one event/action for experiment metrics
                    const entity = events?.[0] || actions?.[0]
                    const metricConfig = filterToMetricConfig(entity as EventsNode | ActionsNode)
                    if (metricConfig) {
                        setSharedMetric({
                            ...sharedMetric,
                            query: {
                                ...sharedMetric.query,
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
        </>
    )
}

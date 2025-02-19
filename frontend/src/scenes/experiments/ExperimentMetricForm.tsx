import { DataWarehousePopoverField } from 'lib/components/TaxonomicFilter/types'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'

import { Query } from '~/queries/Query/Query'
import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { commonActionFilterProps } from './Metrics/Selectors'
import {
    filterToMetricConfig,
    getAllowedMathTypes,
    getMathAvailability,
    metricConfigToFilter,
    metricToQuery,
} from './utils'

const dataWarehousePopoverFields: DataWarehousePopoverField[] = [
    {
        key: 'timestamp_field',
        label: 'Timestamp Field',
    },
    {
        key: 'after_exposure_identifier_field',
        label: 'Data Warehouse Identifier Field',
        allowHogQL: true,
    },
    {
        key: 'exposure_identifier_field',
        label: 'Event Identifier Field',
        allowHogQL: true,
        hogQLOnly: true,
        tableName: 'events',
    },
]

export function ExperimentMetricForm({
    metric,
    handleSetMetric,
}: {
    metric: ExperimentMetric
    handleSetMetric: any
}): JSX.Element {
    const mathAvailability = getMathAvailability(metric.metric_type)
    const allowedMathTypes = getAllowedMathTypes(metric.metric_type)

    const isDataWarehouseMetric = metric.metric_config.kind === NodeKind.ExperimentDataWarehouseMetricConfig

    return (
        <div className="space-y-4">
            <div>
                <h4 className="mb-2">Metric type</h4>
                <LemonRadio
                    data-attr="metrics-selector"
                    value={metric.metric_type}
                    onChange={(newMetricType: ExperimentMetricType) => {
                        const newAllowedMathTypes = getAllowedMathTypes(newMetricType)
                        handleSetMetric({
                            newMetric: {
                                ...metric,
                                metric_type: newMetricType,
                                metric_config: {
                                    ...metric.metric_config,
                                    math: newAllowedMathTypes[0],
                                },
                            },
                        })
                    }}
                    options={[
                        {
                            value: ExperimentMetricType.BINOMIAL,
                            label: 'Binomial',
                            description:
                                'Tracks whether an event happens for each user, useful for measuring conversion rates.',
                        },
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
                setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                    // We only support one event/action for experiment metrics
                    const entity = events?.[0] || actions?.[0] || data_warehouse?.[0]
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
                mathAvailability={mathAvailability}
                allowedMathTypes={allowedMathTypes}
                dataWarehousePopoverFields={dataWarehousePopoverFields}
                {...commonActionFilterProps}
            />
            {/* :KLUDGE: Query chart type is inferred from the initial state, so need to render Trends and Funnels separately */}
            {(metric.metric_type === ExperimentMetricType.COUNT ||
                metric.metric_type === ExperimentMetricType.CONTINUOUS) &&
                !isDataWarehouseMetric && (
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
                )}
            {metric.metric_type === ExperimentMetricType.BINOMIAL && !isDataWarehouseMetric && (
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
            )}
        </div>
    )
}

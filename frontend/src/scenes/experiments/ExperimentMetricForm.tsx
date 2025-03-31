import { DataWarehousePopoverField } from 'lib/components/TaxonomicFilter/types'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'

import { Query } from '~/queries/Query/Query'
import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { commonActionFilterProps } from './Metrics/Selectors'
import {
    filterToMetricConfig,
    getAllowedMathTypes,
    getDefaultExperimentMetric,
    getMathAvailability,
    metricToFilter,
    metricToQuery,
} from './utils'

const dataWarehousePopoverFields: DataWarehousePopoverField[] = [
    {
        key: 'timestamp_field',
        label: 'Timestamp Field',
    },
    {
        key: 'data_warehouse_join_key',
        label: 'Data Warehouse Join Key',
        allowHogQL: true,
    },
    {
        key: 'events_join_key',
        label: 'Events Join Key',
        allowHogQL: true,
        hogQLOnly: true,
        tableName: 'events',
    },
]

export function ExperimentMetricForm({
    metric,
    handleSetMetric,
    filterTestAccounts,
}: {
    metric: ExperimentMetric
    handleSetMetric: (newMetric: ExperimentMetric) => void
    filterTestAccounts: boolean
}): JSX.Element {
    const mathAvailability = getMathAvailability(metric.metric_type)
    const allowedMathTypes = getAllowedMathTypes(metric.metric_type)

    const handleSetFilters = ({ actions, events, data_warehouse }: Partial<FilterType>): void => {
        const metricConfig = filterToMetricConfig(metric.metric_type, actions, events, data_warehouse)
        if (metricConfig) {
            handleSetMetric({
                ...metric,
                ...metricConfig,
            })
        }
    }

    return (
        <div className="deprecated-space-y-4">
            <div>
                <LemonLabel className="mb-1">Type</LemonLabel>
                <LemonRadio
                    data-attr="metrics-selector"
                    value={metric.metric_type}
                    onChange={(newMetricType: ExperimentMetricType) => {
                        handleSetMetric(getDefaultExperimentMetric(newMetricType))
                    }}
                    options={[
                        {
                            value: ExperimentMetricType.FUNNEL,
                            label: 'Funnel',
                            description:
                                'Calculates the percentage of users for whom the metric occurred at least once, useful for measuring conversion rates.',
                        },
                        {
                            value: ExperimentMetricType.MEAN,
                            label: 'Mean',
                            description:
                                'Tracks the value of the metric per user, useful for measuring count of clicks, revenue, or other numeric metrics such as session length.',
                        },
                    ]}
                />
            </div>
            <div>
                <LemonLabel className="mb-1">Metric</LemonLabel>

                {metric.metric_type === ExperimentMetricType.MEAN && (
                    <ActionFilter
                        bordered
                        filters={metricToFilter(metric)}
                        setFilters={handleSetFilters}
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
                )}

                {metric.metric_type === ExperimentMetricType.FUNNEL && (
                    <ActionFilter
                        bordered
                        filters={metricToFilter(metric)}
                        setFilters={handleSetFilters}
                        typeKey="experiment-metric"
                        buttonCopy="Add step"
                        showSeriesIndicator={false}
                        hideRename={true}
                        sortable={true}
                        showNestedArrow={true}
                        // showNumericalPropsOnly={true}
                        mathAvailability={mathAvailability}
                        allowedMathTypes={allowedMathTypes}
                        dataWarehousePopoverFields={dataWarehousePopoverFields}
                        {...commonActionFilterProps}
                    />
                )}
            </div>
            {/* :KLUDGE: Query chart type is inferred from the initial state, so need to render Trends and Funnels separately */}
            {metric.metric_type === ExperimentMetricType.MEAN &&
                metric.source.kind !== NodeKind.ExperimentDataWarehouseNode && (
                    <Query
                        query={{
                            kind: NodeKind.InsightVizNode,
                            source: metricToQuery(metric, filterTestAccounts),
                            showTable: false,
                            showLastComputation: true,
                            showLastComputationRefresh: false,
                        }}
                        readOnly
                    />
                )}
            {metric.metric_type === ExperimentMetricType.FUNNEL && (
                <Query
                    query={{
                        kind: NodeKind.InsightVizNode,
                        source: metricToQuery(metric, filterTestAccounts),
                        showTable: false,
                        showLastComputation: true,
                        showLastComputationRefresh: false,
                    }}
                    readOnly
                />
            )}
            <div>
                <LemonLabel
                    className="mb-1"
                    info={
                        <>
                            Controls how long a metric value is considered relevant to an experiment exposure:
                            <ul className="list-disc pl-4">
                                <li>
                                    <strong>Experiment duration</strong> considers any data from when a user is first
                                    exposed until the experiment ends.
                                </li>
                                <li>
                                    <strong>Conversion window</strong> only includes data that occurs within the
                                    specified number of hours after a user's first exposure (also ignoring the
                                    experiment end date).
                                </li>
                            </ul>
                        </>
                    }
                >
                    Time window
                </LemonLabel>
                <div className="flex items-center gap-2">
                    <LemonRadio
                        className="my-1.5"
                        value={metric.time_window_hours === undefined ? 'full' : 'conversion'}
                        orientation="horizontal"
                        onChange={(value) =>
                            handleSetMetric({
                                ...metric,
                                time_window_hours: value === 'full' ? undefined : 72,
                            })
                        }
                        options={[
                            {
                                value: 'full',
                                label: 'Experiment duration',
                            },
                            {
                                value: 'conversion',
                                label: 'Conversion window',
                            },
                        ]}
                    />
                    {metric.time_window_hours !== undefined && (
                        <LemonInput
                            value={metric.time_window_hours}
                            onChange={(value) => handleSetMetric({ ...metric, time_window_hours: value || undefined })}
                            type="number"
                            step={1}
                            suffix={<span className="text-sm">hours</span>}
                            size="small"
                        />
                    )}
                </div>
            </div>
        </div>
    )
}

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
    handleSetMetric: any
    filterTestAccounts: boolean
}): JSX.Element {
    const mathAvailability = getMathAvailability(metric.metric_type)
    const allowedMathTypes = getAllowedMathTypes(metric.metric_type)

    const isDataWarehouseMetric = metric.metric_config.kind === NodeKind.ExperimentDataWarehouseMetricConfig

    return (
        <div className="space-y-4">
            <div>
                <LemonLabel className="mb-1">Type</LemonLabel>
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
                                'Calculates the percentage of users for whom the metric occurred at least once, useful for measuring conversion rates.',
                        },
                        {
                            value: ExperimentMetricType.COUNT,
                            label: 'Count',
                            description:
                                'Tracks how many times the metric occurs per user, useful for measuring click counts or page views.',
                        },
                        {
                            value: ExperimentMetricType.CONTINUOUS,
                            label: 'Continuous',
                            description: 'Measures numerical values of the metric, such as revenue or session length.',
                        },
                    ]}
                />
            </div>
            <div>
                <LemonLabel className="mb-1">Metric</LemonLabel>
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
            </div>
            {/* :KLUDGE: Query chart type is inferred from the initial state, so need to render Trends and Funnels separately */}
            {(metric.metric_type === ExperimentMetricType.COUNT ||
                metric.metric_type === ExperimentMetricType.CONTINUOUS) &&
                !isDataWarehouseMetric && (
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
            {metric.metric_type === ExperimentMetricType.BINOMIAL && !isDataWarehouseMetric && (
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
                                newMetric: {
                                    ...metric,
                                    time_window_hours: value === 'full' ? undefined : 72,
                                },
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
                            onChange={(value) =>
                                handleSetMetric({ newMetric: { ...metric, time_window_hours: value || undefined } })
                            }
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

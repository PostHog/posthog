import { DataWarehousePopoverField } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'

import { Query } from '~/queries/Query/Query'
import { ExperimentMetric, ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { ExperimentMetricConversionWindowFilter } from './ExperimentMetricConversionWindowFilter'
import { ExperimentMetricOutlierHandling } from './ExperimentMetricOutlierHandling'
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
            <ExperimentMetricConversionWindowFilter metric={metric} handleSetMetric={handleSetMetric} />
            {metric.metric_type === ExperimentMetricType.MEAN && (
                <ExperimentMetricOutlierHandling metric={metric} handleSetMetric={handleSetMetric} />
            )}
        </div>
    )
}

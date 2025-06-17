import { DataWarehousePopoverField } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'

import { Query } from '~/queries/Query/Query'
import {
    ExperimentMetric,
    ExperimentMetricType,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    NodeKind,
} from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { ExperimentMetricConversionWindowFilter } from './ExperimentMetricConversionWindowFilter'
import { ExperimentMetricFunnelOrderSelector } from './ExperimentMetricFunnelOrderSelector'
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

    const handleMetricTypeChange = (newMetricType: ExperimentMetricType): void => {
        handleSetMetric(getDefaultExperimentMetric(newMetricType))
    }

    const radioOptions = [
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
    ]

    const metricFilter = metricToFilter(metric)
    const previewQuery = metricToQuery(metric, filterTestAccounts)

    const queryConfig = {
        kind: NodeKind.InsightVizNode,
        source: previewQuery,
        showTable: false,
        showLastComputation: true,
        showLastComputationRefresh: false,
    }

    const hideDeleteBtn = (_: any, index: number): boolean => index === 0

    return (
        <div className="deprecated-space-y-4">
            <div>
                <LemonLabel className="mb-1">Type</LemonLabel>
                <LemonRadio
                    data-attr="metrics-selector"
                    value={metric.metric_type}
                    onChange={handleMetricTypeChange}
                    options={radioOptions}
                />
            </div>
            <div>
                <LemonLabel className="mb-1">Metric</LemonLabel>

                {metric.metric_type === ExperimentMetricType.MEAN && (
                    <ActionFilter
                        bordered
                        filters={metricFilter}
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
                        filters={metricFilter}
                        setFilters={handleSetFilters}
                        typeKey="experiment-metric"
                        buttonCopy="Add step"
                        showSeriesIndicator={false}
                        hideRename={true}
                        hideDeleteBtn={hideDeleteBtn}
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
            <ExperimentMetricConversionWindowFilter metric={metric} handleSetMetric={handleSetMetric} />
            {isExperimentFunnelMetric(metric) && (
                <ExperimentMetricFunnelOrderSelector metric={metric} handleSetMetric={handleSetMetric} />
            )}
            {isExperimentMeanMetric(metric) && (
                <ExperimentMetricOutlierHandling metric={metric} handleSetMetric={handleSetMetric} />
            )}
            <div>
                <LemonLabel
                    className="mb-1"
                    info={
                        <>
                            The preview uses data from the past 14 days to show how the metric will appear.
                            <br />
                            For funnel metrics, we simulate experiment exposure by inserting a page-view event at the
                            start of the funnel. In the experiment evaluation, this will be replaced by the actual
                            experiment-exposure event.
                        </>
                    }
                >
                    Preview
                </LemonLabel>
            </div>
            {/* :KLUDGE: Query chart type is inferred from the initial state, so need to render Trends and Funnels separately */}
            {isExperimentMeanMetric(metric) && metric.source.kind !== NodeKind.ExperimentDataWarehouseNode && (
                <Query query={queryConfig} readOnly />
            )}
            {isExperimentFunnelMetric(metric) && <Query query={queryConfig} readOnly />}
        </div>
    )
}

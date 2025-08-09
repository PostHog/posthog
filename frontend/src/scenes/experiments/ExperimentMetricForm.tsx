import { DataWarehousePopoverField } from 'lib/components/TaxonomicFilter/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { Link } from 'lib/lemon-ui/Link'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { useEffect, useState } from 'react'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { performQuery } from '~/queries/query'
import {
    ExperimentMetric,
    ExperimentMetricType,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ExperimentMetricMathType, FilterType } from '~/types'

import { ExperimentMetricConversionWindowFilter } from './ExperimentMetricConversionWindowFilter'
import { ExperimentMetricFunnelOrderSelector } from './ExperimentMetricFunnelOrderSelector'
import { ExperimentMetricOutlierHandling } from './ExperimentMetricOutlierHandling'
import { commonActionFilterProps } from './Metrics/Selectors'
import {
    filterToMetricConfig,
    getAllowedMathTypes,
    getDefaultExperimentMetric,
    getMathAvailability,
    getEventCountQuery,
} from './utils'

import { getFilter } from './metricQueryUtils'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

const loadEventCount = async (
    metric: ExperimentMetric,
    filterTestAccounts: boolean,
    setEventCount: (count: number | null) => void,
    setIsLoading: (loading: boolean) => void
): Promise<void> => {
    setIsLoading(true)
    try {
        const query = getEventCountQuery(metric, filterTestAccounts)

        if (!query) {
            setEventCount(0)
            return
        }

        const response = await performQuery(query)

        let count = 0
        if (response.results.length > 0) {
            const firstResult = response.results[0]
            if (firstResult && typeof firstResult.aggregated_value === 'number') {
                count = firstResult.aggregated_value
            }
        }

        setEventCount(count)
    } catch (error) {
        lemonToast.error(JSON.stringify(error))
        setEventCount(0)
    } finally {
        setIsLoading(false)
    }
}

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
    const [eventCount, setEventCount] = useState<number | null>(null)
    const [isLoading, setIsLoading] = useState(false)

    const getEventTypeLabel = (): string => {
        if (metric.metric_type === ExperimentMetricType.MEAN) {
            return metric.source.kind === NodeKind.ActionsNode ? 'actions' : 'events'
        } else if (metric.metric_type === ExperimentMetricType.FUNNEL) {
            const lastStep = metric.series[metric.series.length - 1]
            return lastStep?.kind === NodeKind.ActionsNode ? 'actions' : 'events'
        } else if (metric.metric_type === ExperimentMetricType.RATIO) {
            return 'events'
        }
        return 'events'
    }

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
        {
            value: ExperimentMetricType.RATIO,
            label: 'Ratio',
            description:
                'Calculates the ratio between two metrics, useful for measuring metrics like revenue per purchase or page views per session.',
        },
    ]

    const metricFilter = getFilter(metric)

    useEffect(
        () => {
            loadEventCount(metric, filterTestAccounts, setEventCount, setIsLoading)
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [
            metric.metric_type,
            isExperimentMeanMetric(metric) ? metric.source : null,
            isExperimentFunnelMetric(metric) ? metric.series : null,
            isExperimentRatioMetric(metric) ? [metric.numerator, metric.denominator] : null,
            filterTestAccounts,
        ]
    )

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
                    <>
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
                        {isExperimentMeanMetric(metric) && metric.source.math === ExperimentMetricMathType.HogQL && (
                            <div className="text-muted text-sm mt-2">
                                SQL expressions allow you to write custom computations and aggregations. The expression
                                should return a numeric value and will be evaluated for each user in the experiment.{' '}
                                <Link
                                    to="https://posthog.com/docs/hogql/expressions"
                                    target="_blank"
                                    disableDocsPanel={true}
                                >
                                    Learn more about HogQL expressions
                                </Link>
                            </div>
                        )}
                    </>
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
                        // Data warehouse is not supported for funnel metrics - enforced at schema level
                        actionsTaxonomicGroupTypes={commonActionFilterProps.actionsTaxonomicGroupTypes?.filter(
                            (type) => type !== 'data_warehouse'
                        )}
                        propertiesTaxonomicGroupTypes={commonActionFilterProps.propertiesTaxonomicGroupTypes}
                    />
                )}

                {metric.metric_type === ExperimentMetricType.RATIO && (
                    <div className="space-y-4">
                        <div>
                            <LemonLabel className="mb-1">Numerator (what you're measuring)</LemonLabel>
                            <ActionFilter
                                bordered
                                filters={{
                                    events: isExperimentRatioMetric(metric)
                                        ? [
                                              {
                                                  id: metric.numerator.event || '',
                                                  name: metric.numerator.name || metric.numerator.event || '',
                                                  type: 'events',
                                                  kind: metric.numerator.kind,
                                                  event: metric.numerator.event,
                                                  math: metric.numerator.math,
                                                  math_property: metric.numerator.math_property,
                                                  properties: metric.numerator.properties,
                                              },
                                          ]
                                        : [],
                                    actions: [],
                                    data_warehouse: [],
                                }}
                                setFilters={(filters) => {
                                    if (isExperimentRatioMetric(metric) && filters.events?.[0]) {
                                        handleSetMetric({
                                            ...metric,
                                            numerator: {
                                                kind: NodeKind.EventsNode,
                                                event: filters.events[0].id,
                                                name: filters.events[0].name,
                                                math: filters.events[0].math,
                                                math_property: filters.events[0].math_property,
                                                properties: filters.events[0].properties,
                                            },
                                        })
                                    }
                                }}
                                typeKey="experiment-metric-numerator"
                                buttonCopy="Add numerator event"
                                showSeriesIndicator={false}
                                hideRename={true}
                                entitiesLimit={1}
                                showNumericalPropsOnly={true}
                                mathAvailability={mathAvailability}
                                allowedMathTypes={allowedMathTypes}
                                actionsTaxonomicGroupTypes={commonActionFilterProps.actionsTaxonomicGroupTypes?.filter(
                                    (type) => type !== 'data_warehouse'
                                )}
                                propertiesTaxonomicGroupTypes={commonActionFilterProps.propertiesTaxonomicGroupTypes}
                            />
                        </div>
                        <div>
                            <LemonLabel className="mb-1">Denominator (what you're dividing by)</LemonLabel>
                            <ActionFilter
                                bordered
                                filters={{
                                    events: isExperimentRatioMetric(metric)
                                        ? [
                                              {
                                                  id: metric.denominator.event || '',
                                                  name: metric.denominator.name || metric.denominator.event || '',
                                                  type: 'events',
                                                  kind: metric.denominator.kind,
                                                  event: metric.denominator.event,
                                                  math: metric.denominator.math,
                                                  math_property: metric.denominator.math_property,
                                                  properties: metric.denominator.properties,
                                              },
                                          ]
                                        : [],
                                    actions: [],
                                    data_warehouse: [],
                                }}
                                setFilters={(filters) => {
                                    if (isExperimentRatioMetric(metric) && filters.events?.[0]) {
                                        handleSetMetric({
                                            ...metric,
                                            denominator: {
                                                kind: NodeKind.EventsNode,
                                                event: filters.events[0].id,
                                                name: filters.events[0].name,
                                                math: filters.events[0].math,
                                                math_property: filters.events[0].math_property,
                                                properties: filters.events[0].properties,
                                            },
                                        })
                                    }
                                }}
                                typeKey="experiment-metric-denominator"
                                buttonCopy="Add denominator event"
                                showSeriesIndicator={false}
                                hideRename={true}
                                entitiesLimit={1}
                                mathAvailability={mathAvailability}
                                allowedMathTypes={allowedMathTypes}
                                actionsTaxonomicGroupTypes={commonActionFilterProps.actionsTaxonomicGroupTypes?.filter(
                                    (type) => type !== 'data_warehouse'
                                )}
                                propertiesTaxonomicGroupTypes={commonActionFilterProps.propertiesTaxonomicGroupTypes}
                            />
                        </div>
                    </div>
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
                        <div className="flex flex-col gap-2">
                            <div>This shows recent activity for your selected metric over the past 2 weeks.</div>
                            <div>
                                It's a quick health check to ensure your tracking is working properly, so that you'll
                                receive accurate results when your experiment starts.
                            </div>
                            <div>
                                If you see zero activity, double-check that this metric is being tracked properly in
                                your application. Head to{' '}
                                <Link target="_blank" className="font-semibold" to={urls.insightNew()}>
                                    Product analytics
                                    <IconOpenInNew fontSize="18" />
                                </Link>{' '}
                                to do a detailed analysis of the events received so far.
                            </div>
                        </div>
                    }
                >
                    Recent activity
                </LemonLabel>
                <div className="border rounded p-4 bg-bg-light">
                    {isLoading ? (
                        <div className="flex items-center gap-2">
                            <Spinner />
                            <span className="text-muted">Loading recent activity...</span>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-1">
                            <div className="text-2xl font-semibold">
                                {eventCount !== null ? eventCount.toLocaleString() : '0'}
                            </div>
                            <div className="text-sm text-muted">
                                {eventCount !== null && eventCount > 0
                                    ? `${getEventTypeLabel()} in the past 2 weeks`
                                    : 'No recent activity'}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}

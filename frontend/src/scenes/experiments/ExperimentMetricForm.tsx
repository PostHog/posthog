import { useEffect, useState } from 'react'

import { DataWarehousePopoverField } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import {
    ExperimentMetric,
    ExperimentMetricType,
    NodeKind,
    isExperimentFunnelMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
} from '~/queries/schema/schema-general'
import { ExperimentMetricMathType, FilterType } from '~/types'

import { ExperimentMetricConversionWindowFilter } from './ExperimentMetricConversionWindowFilter'
import { ExperimentMetricFunnelOrderSelector } from './ExperimentMetricFunnelOrderSelector'
import { ExperimentMetricOutlierHandling } from './ExperimentMetricOutlierHandling'
import { commonActionFilterProps } from './Metrics/Selectors'
import { filterToMetricConfig, filterToMetricSource } from './metricQueryUtils'
import { createFilterForSource, getFilter } from './metricQueryUtils'
import { getAllowedMathTypes, getDefaultExperimentMetric, getEventCountQuery, getMathAvailability } from './utils'

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

    // if the metric already is a ratio metric, we want to show the option regardless of the feature state
    const isRatioMetricEnabled = useFeatureFlag('EXPERIMENTS_RATIO_METRIC') || isExperimentRatioMetric(metric)

    const getEventTypeLabel = (): string => {
        if (isExperimentMeanMetric(metric)) {
            return metric.source.kind === NodeKind.ActionsNode ? 'actions' : 'events'
        } else if (isExperimentFunnelMetric(metric)) {
            const lastStep = metric.series[metric.series.length - 1]
            return lastStep?.kind === NodeKind.ActionsNode ? 'actions' : 'events'
        } else if (isExperimentRatioMetric(metric)) {
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
                'Calculates the percentage of users exposed to the experiment who completed the funnel. Useful for measuring conversion rates.',
        },
        {
            value: ExperimentMetricType.MEAN,
            label: 'Mean',
            description:
                'Calculates the value per user exposed to the experiment. Useful for measuring count of clicks, revenue or other numeric values.',
        },
        ...(isRatioMetricEnabled
            ? [
                  {
                      value: ExperimentMetricType.RATIO,
                      label: 'Ratio',
                      description:
                          'Calculates the ratio between two metrics. Useful when you want to use a different denominator than users exposed to the experiment.',
                  },
              ]
            : []),
    ]

    const metricFilter = getFilter(metric)

    // dependencies for the loadEventCount useEffect call
    const meanSource = isExperimentMeanMetric(metric) ? metric.source : null
    const funnelSeries = isExperimentFunnelMetric(metric) ? metric.series : null
    const ratioNumerator = isExperimentRatioMetric(metric) ? metric.numerator : null
    const ratioDenominator = isExperimentRatioMetric(metric) ? metric.denominator : null

    useEffect(() => {
        loadEventCount(metric, filterTestAccounts, setEventCount, setIsLoading)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [metric.metric_type, meanSource, funnelSeries, ratioNumerator, ratioDenominator, filterTestAccounts])

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

                {isExperimentMeanMetric(metric) && (
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
                        {metric.source.math === ExperimentMetricMathType.HogQL && (
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

                {isExperimentFunnelMetric(metric) && (
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

                {isExperimentRatioMetric(metric) && (
                    <div className="space-y-4">
                        <div>
                            <LemonLabel className="mb-1">Numerator (what you're measuring)</LemonLabel>
                            <ActionFilter
                                bordered
                                filters={createFilterForSource(metric.numerator)}
                                setFilters={(filters) => {
                                    const source = filterToMetricSource(
                                        filters.actions,
                                        filters.events,
                                        filters.data_warehouse
                                    )
                                    if (source) {
                                        handleSetMetric({
                                            ...metric,
                                            numerator: source,
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
                                dataWarehousePopoverFields={dataWarehousePopoverFields}
                                {...commonActionFilterProps}
                            />
                        </div>
                        <div>
                            <LemonLabel className="mb-1">Denominator (what you're dividing by)</LemonLabel>
                            <ActionFilter
                                bordered
                                filters={createFilterForSource(metric.denominator)}
                                setFilters={(filters) => {
                                    const source = filterToMetricSource(
                                        filters.actions,
                                        filters.events,
                                        filters.data_warehouse
                                    )
                                    if (source) {
                                        handleSetMetric({
                                            ...metric,
                                            denominator: source,
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
                                dataWarehousePopoverFields={dataWarehousePopoverFields}
                                {...commonActionFilterProps}
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

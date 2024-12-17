import { IconInfo, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDivider, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { EXPERIMENT_DEFAULT_DURATION, FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useState } from 'react'

import { ExperimentFunnelsQuery, ExperimentTrendsQuery, FunnelsQuery, NodeKind, TrendsQuery } from '~/queries/schema'
import { ActionFilter, AnyPropertyFilter, ChartDisplayType, Experiment, FilterType, InsightType } from '~/types'

import { experimentLogic, getDefaultFilters, getDefaultFunnelsMetric } from '../experimentLogic'
import { PrimaryMetricModal } from '../Metrics/PrimaryMetricModal'
import { PrimaryTrendsExposureModal } from '../Metrics/PrimaryTrendsExposureModal'

export function MetricDisplayTrends({ query }: { query: TrendsQuery | undefined }): JSX.Element {
    const event = query?.series?.[0] as unknown as ActionFilter

    if (!event) {
        return <></>
    }

    return (
        <>
            <div className="mb-2">
                <div className="flex mb-1">
                    <b>
                        <InsightLabel action={event} showCountedByTag={true} hideIcon showEventName />
                    </b>
                </div>
                <div className="space-y-1">
                    {event.properties?.map((prop: AnyPropertyFilter) => (
                        <PropertyFilterButton key={prop.key} item={prop} />
                    ))}
                </div>
            </div>
        </>
    )
}

export function MetricDisplayFunnels({ query }: { query: FunnelsQuery }): JSX.Element {
    return (
        <>
            {(query.series || []).map((event: any, idx: number) => (
                <div key={idx} className="mb-2">
                    <div className="flex mb-1">
                        <div
                            className="shrink-0 w-6 h-6 mr-2 font-bold text-center text-primary-alt border rounded"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: 'var(--background-primary)' }}
                        >
                            {idx + 1}
                        </div>
                        <b>
                            <InsightLabel action={event} hideIcon showEventName />
                        </b>
                    </div>
                    <div className="space-y-1">
                        {event.properties?.map((prop: AnyPropertyFilter) => (
                            <PropertyFilterButton key={prop.key} item={prop} />
                        ))}
                    </div>
                </div>
            ))}
        </>
    )
}

// :FLAG: CLEAN UP AFTER MIGRATION
export function MetricDisplayOld({ filters }: { filters?: FilterType }): JSX.Element {
    const metricType = filters?.insight || InsightType.TRENDS

    return (
        <>
            {(
                [
                    ...(filters?.events || []),
                    ...(filters?.actions || []),
                    ...(filters?.data_warehouse || []),
                ] as ActionFilter[]
            )
                .sort((a, b) => (a.order || 0) - (b.order || 0))
                .map((event: ActionFilter, idx: number) => (
                    <div key={idx} className="mb-2">
                        <div className="flex mb-1">
                            {metricType === InsightType.FUNNELS && (
                                <div
                                    className="shrink-0 w-6 h-6 mr-2 font-bold text-center text-primary-alt border rounded"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ backgroundColor: 'var(--background-primary)' }}
                                >
                                    {(event.order || 0) + 1}
                                </div>
                            )}
                            <b>
                                <InsightLabel
                                    action={event}
                                    showCountedByTag={metricType === InsightType.TRENDS}
                                    hideIcon
                                    showEventName
                                />
                            </b>
                        </div>
                        <div className="space-y-1">
                            {event.properties?.map((prop: AnyPropertyFilter) => (
                                <PropertyFilterButton key={prop.key} item={prop} />
                            ))}
                        </div>
                    </div>
                ))}
        </>
    )
}

export function ExposureMetric({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, featureFlags } = useValues(experimentLogic({ experimentId }))
    const { updateExperimentExposure, loadExperiment, setExperiment } = useActions(experimentLogic({ experimentId }))
    const [isModalOpen, setIsModalOpen] = useState(false)

    const metricIdx = 0

    // :FLAG: CLEAN UP AFTER MIGRATION
    let hasCustomExposure = false
    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
        hasCustomExposure = !!(experiment.metrics[metricIdx] as ExperimentTrendsQuery).exposure_query
    } else {
        hasCustomExposure = !!experiment.parameters?.custom_exposure_filter
    }

    return (
        <>
            <div className="card-secondary mb-2 mt-2">
                Exposure metric
                <Tooltip
                    title={`This metric determines how we calculate exposure for the experiment. Only users who have this event alongside the property '$feature/${experiment.feature_flag_key}' are included in the exposure calculations.`}
                >
                    <IconInfo className="ml-1 text-muted text-sm" />
                </Tooltip>
            </div>
            {/* :FLAG: CLEAN UP AFTER MIGRATION */}
            {featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL] ? (
                hasCustomExposure ? (
                    <MetricDisplayTrends query={(experiment.metrics[0] as ExperimentTrendsQuery).exposure_query} />
                ) : (
                    <span className="description">Default via $feature_flag_called events</span>
                )
            ) : hasCustomExposure ? (
                <MetricDisplayOld filters={experiment.parameters.custom_exposure_filter} />
            ) : (
                <span className="description">Default via $feature_flag_called events</span>
            )}
            <div className="mb-2 mt-2">
                <span className="flex">
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={() => {
                            if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                                if (!hasCustomExposure) {
                                    setExperiment({
                                        ...experiment,
                                        metrics: experiment.metrics.map((metric, idx) =>
                                            idx === metricIdx
                                                ? {
                                                      ...metric,
                                                      exposure_query: {
                                                          kind: NodeKind.TrendsQuery,
                                                          series: [
                                                              {
                                                                  kind: NodeKind.EventsNode,
                                                                  name: '$pageview',
                                                                  event: '$pageview',
                                                              },
                                                          ],
                                                          interval: 'day',
                                                          dateRange: {
                                                              date_from: dayjs()
                                                                  .subtract(EXPERIMENT_DEFAULT_DURATION, 'day')
                                                                  .format('YYYY-MM-DDTHH:mm'),
                                                              date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                                                              explicitDate: true,
                                                          },
                                                          trendsFilter: {
                                                              display: ChartDisplayType.ActionsLineGraph,
                                                          },
                                                          filterTestAccounts: true,
                                                      },
                                                  }
                                                : metric
                                        ),
                                    })
                                }
                            } else {
                                if (!hasCustomExposure) {
                                    setExperiment({
                                        ...experiment,
                                        parameters: {
                                            ...experiment.parameters,
                                            custom_exposure_filter: getDefaultFilters(InsightType.TRENDS, undefined),
                                        },
                                    })
                                }
                            }
                            setIsModalOpen(true)
                        }}
                        className="mr-2"
                    >
                        Change exposure metric
                    </LemonButton>
                    {hasCustomExposure && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="xsmall"
                            onClick={() => {
                                // :FLAG: CLEAN UP AFTER MIGRATION
                                if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                                    setExperiment({
                                        ...experiment,
                                        metrics: experiment.metrics.map((metric, idx) =>
                                            idx === metricIdx ? { ...metric, exposure_query: undefined } : metric
                                        ),
                                    })
                                }
                                updateExperimentExposure(null)
                            }}
                        >
                            Reset
                        </LemonButton>
                    )}
                </span>
            </div>
            <PrimaryTrendsExposureModal
                experimentId={experimentId}
                isOpen={isModalOpen}
                onClose={() => {
                    setIsModalOpen(false)
                    loadExperiment()
                }}
            />
        </>
    )
}

export function Goal(): JSX.Element {
    const { experiment, experimentId, getMetricType, experimentMathAggregationForTrends, hasGoalSet, featureFlags } =
        useValues(experimentLogic)
    const { setExperiment, loadExperiment } = useActions(experimentLogic)
    const [isModalOpen, setIsModalOpen] = useState(false)
    const metricType = getMetricType(0)

    // :FLAG: CLEAN UP AFTER MIGRATION
    const isDataWarehouseMetric =
        featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL] &&
        metricType === InsightType.TRENDS &&
        (experiment.metrics[0] as ExperimentTrendsQuery).count_query?.series[0].kind === NodeKind.DataWarehouseNode

    return (
        <div>
            <div>
                <div className="inline-flex space-x-2">
                    <h2 className="font-semibold text-lg mb-0">Experiment goal</h2>
                    <Tooltip
                        title={
                            <>
                                {' '}
                                This <b>{metricType === InsightType.FUNNELS ? 'funnel' : 'trend'}</b>{' '}
                                {metricType === InsightType.FUNNELS
                                    ? 'experiment measures conversion at each stage.'
                                    : 'experiment tracks the count of a single metric.'}
                            </>
                        }
                    >
                        <IconInfo className="text-[var(--content-tertiary)] text-base" />
                    </Tooltip>
                </div>
            </div>
            {!hasGoalSet ? (
                <div className="text-muted">
                    <div className="text-sm text-balance mt-2 mb-2">
                        Add the main goal before launching the experiment.
                    </div>
                    <LemonButton
                        icon={<IconPlus />}
                        type="secondary"
                        size="small"
                        data-attr="add-experiment-goal"
                        onClick={() => {
                            if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                                setExperiment({
                                    ...experiment,
                                    metrics: [getDefaultFunnelsMetric()],
                                })
                            } else {
                                setExperiment({
                                    ...experiment,
                                    filters: getDefaultFilters(InsightType.FUNNELS, undefined),
                                })
                            }
                            setIsModalOpen(true)
                        }}
                    >
                        Add goal
                    </LemonButton>
                </div>
            ) : (
                <div className="inline-flex space-x-6">
                    <div>
                        <div className="card-secondary mb-2 mt-2">
                            {metricType === InsightType.FUNNELS ? 'Conversion goal steps' : 'Trend goal'}
                        </div>
                        {/* :FLAG: CLEAN UP AFTER MIGRATION */}
                        {featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL] ? (
                            metricType === InsightType.FUNNELS ? (
                                <MetricDisplayFunnels
                                    query={(experiment.metrics[0] as ExperimentFunnelsQuery).funnels_query}
                                />
                            ) : (
                                <MetricDisplayTrends
                                    query={(experiment.metrics[0] as ExperimentTrendsQuery).count_query}
                                />
                            )
                        ) : (
                            <MetricDisplayOld filters={experiment.filters} />
                        )}
                        <LemonButton size="xsmall" type="secondary" onClick={() => setIsModalOpen(true)}>
                            Change goal
                        </LemonButton>
                    </div>
                    {metricType === InsightType.TRENDS &&
                        !experimentMathAggregationForTrends() &&
                        !isDataWarehouseMetric && (
                            <>
                                <LemonDivider className="" vertical />
                                <div className="">
                                    <div className="mt-auto ml-auto">
                                        <ExposureMetric experimentId={experimentId} />
                                    </div>
                                </div>
                            </>
                        )}
                </div>
            )}
            <PrimaryMetricModal
                experimentId={experimentId}
                isOpen={isModalOpen}
                onClose={() => {
                    setIsModalOpen(false)
                    loadExperiment()
                }}
            />
        </div>
    )
}

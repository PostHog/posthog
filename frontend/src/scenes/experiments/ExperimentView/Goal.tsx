import { IconInfo, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDivider, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useState } from 'react'

import {
    ExperimentFunnelsQuery,
    ExperimentTrendsQuery,
    FunnelsQuery,
    NodeKind,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { ActionFilter, AnyPropertyFilter, ChartDisplayType, Experiment, InsightType } from '~/types'

import { experimentLogic, getDefaultFunnelsMetric } from '../experimentLogic'
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
                            style={{ backgroundColor: 'var(--bg-table)' }}
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

export function ExposureMetric({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment } = useValues(experimentLogic({ experimentId }))
    const { updateExperimentGoal, loadExperiment, setExperiment, setEditingPrimaryMetricIndex } = useActions(
        experimentLogic({ experimentId })
    )
    const [isModalOpen, setIsModalOpen] = useState(false)

    const metricIdx = 0
    const hasCustomExposure = !!(experiment.metrics[metricIdx] as ExperimentTrendsQuery).exposure_query

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
            {hasCustomExposure ? (
                <MetricDisplayTrends query={(experiment.metrics[0] as ExperimentTrendsQuery).exposure_query} />
            ) : (
                <span className="description">Default via $feature_flag_called events</span>
            )}
            <div className="mb-2 mt-2">
                <span className="flex">
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={() => {
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
                            setEditingPrimaryMetricIndex(metricIdx)
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
                                setExperiment({
                                    ...experiment,
                                    metrics: experiment.metrics.map((metric, idx) =>
                                        idx === metricIdx ? { ...metric, exposure_query: undefined } : metric
                                    ),
                                })
                                updateExperimentGoal()
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
                    setEditingPrimaryMetricIndex(null)
                    loadExperiment()
                }}
            />
        </>
    )
}

export function Goal(): JSX.Element {
    const { experiment, experimentId, _getMetricType, experimentMathAggregationForTrends, hasGoalSet } =
        useValues(experimentLogic)
    const { setExperiment, openPrimaryMetricModal } = useActions(experimentLogic)
    const metricType = _getMetricType(experiment.metrics[0])

    const isDataWarehouseMetric =
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
                        <IconInfo className="text-muted-alt text-base" />
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
                            setExperiment({
                                ...experiment,
                                metrics: [getDefaultFunnelsMetric()],
                            })
                            openPrimaryMetricModal(0)
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
                        {metricType === InsightType.FUNNELS ? (
                            <MetricDisplayFunnels
                                query={(experiment.metrics[0] as ExperimentFunnelsQuery).funnels_query}
                            />
                        ) : (
                            <MetricDisplayTrends query={(experiment.metrics[0] as ExperimentTrendsQuery).count_query} />
                        )}
                        <LemonButton size="xsmall" type="secondary" onClick={() => openPrimaryMetricModal(0)}>
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
        </div>
    )
}

import { IconInfo, IconPencil, IconPlus } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'
import { useState } from 'react'

import { Experiment, InsightType } from '~/types'

import {
    experimentLogic,
    getDefaultFilters,
    getDefaultFunnelsMetric,
    TabularSecondaryMetricResults,
} from '../experimentLogic'
import { SecondaryMetricChartModal } from '../Metrics/SecondaryMetricChartModal'
import { SecondaryMetricModal } from '../Metrics/SecondaryMetricModal'
import { VariantTag } from './components'

const MAX_SECONDARY_METRICS = 10

export function SecondaryMetricsTable({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const [isEditModalOpen, setIsEditModalOpen] = useState(false)
    const [isChartModalOpen, setIsChartModalOpen] = useState(false)
    const [modalMetricIdx, setModalMetricIdx] = useState<number | null>(null)

    const {
        experimentResults,
        secondaryMetricResultsLoading,
        experiment,
        getSecondaryMetricType,
        secondaryMetricResults,
        tabularSecondaryMetricResults,
        countDataForVariant,
        exposureCountDataForVariant,
        conversionRateForVariant,
        credibleIntervalForVariant,
        experimentMathAggregationForTrends,
        getHighestProbabilityVariant,
        featureFlags,
    } = useValues(experimentLogic({ experimentId }))
    const { loadExperiment } = useActions(experimentLogic({ experimentId }))

    const openEditModal = (idx: number): void => {
        setModalMetricIdx(idx)
        setIsEditModalOpen(true)
    }

    const closeEditModal = (): void => {
        setIsEditModalOpen(false)
        setModalMetricIdx(null)
        loadExperiment()
    }

    const openChartModal = (idx: number): void => {
        setModalMetricIdx(idx)
        setIsChartModalOpen(true)
    }

    const closeChartModal = (): void => {
        setIsChartModalOpen(false)
        setModalMetricIdx(null)
    }

    // :FLAG: CLEAN UP AFTER MIGRATION
    let metrics
    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
        metrics = experiment.metrics_secondary
    } else {
        metrics = experiment.secondary_metrics
    }

    const columns: LemonTableColumns<any> = [
        {
            children: [
                {
                    title: <div className="py-2">Variant</div>,
                    render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                        if (!experimentResults || !experimentResults.insight) {
                            return <span className="font-semibold">{item.variant}</span>
                        }
                        return (
                            <div className="flex items-center py-2">
                                <VariantTag experimentId={experimentId} variantKey={item.variant} />
                            </div>
                        )
                    },
                },
            ],
        },
    ]

    metrics?.forEach((metric, idx) => {
        const targetResults = secondaryMetricResults?.[idx]
        const winningVariant = getHighestProbabilityVariant(targetResults || null)
        const metricType = getSecondaryMetricType(idx)

        const Header = (): JSX.Element => (
            <div className="">
                <div className="flex">
                    <div className="w-3/4 truncate">{capitalizeFirstLetter(metric.name || '')}</div>
                    <div className="w-1/4 flex flex-col justify-end">
                        <div className="ml-auto space-x-2 pb-1 inline-flex">
                            <LemonButton
                                className="max-w-72"
                                type="secondary"
                                size="xsmall"
                                icon={<IconAreaChart />}
                                onClick={() => openChartModal(idx)}
                                disabledReason={
                                    targetResults && targetResults.insight
                                        ? undefined
                                        : 'There are no results for this metric yet'
                                }
                            />
                            <LemonButton
                                className="max-w-72"
                                type="secondary"
                                size="xsmall"
                                icon={<IconPencil />}
                                onClick={() => openEditModal(idx)}
                            />
                        </div>
                    </div>
                </div>
            </div>
        )

        if (metricType === InsightType.TRENDS) {
            columns.push({
                title: <Header />,
                children: [
                    {
                        title: (
                            <div className="flex">
                                [
                                {targetResults &&
                                    targetResults.insight?.[0] &&
                                    'action' in targetResults.insight[0] && (
                                        <EntityFilterInfo filter={targetResults.insight[0].action} />
                                    )}
                                ]
                                <span className="pl-1">
                                    {experimentMathAggregationForTrends() ? 'metric' : 'count'}
                                </span>
                            </div>
                        ),
                        render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                            const { variant } = item
                            const count = targetResults ? countDataForVariant(targetResults, variant) : null
                            return <div>{count === null ? '—' : humanFriendlyNumber(count)}</div>
                        },
                    },
                    {
                        title: 'Exposure',
                        render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                            const { variant } = item
                            const exposureCount = targetResults
                                ? exposureCountDataForVariant(targetResults, variant)
                                : null
                            return <div>{exposureCount === null ? '—' : humanFriendlyNumber(exposureCount)}</div>
                        },
                    },
                    {
                        title: 'Credible interval (95%)',
                        render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                            if (item.variant === 'control') {
                                return <em>Baseline</em>
                            }
                            const credibleInterval = credibleIntervalForVariant(
                                targetResults || null,
                                item.variant,
                                metricType
                            )
                            if (!credibleInterval) {
                                return <>—</>
                            }
                            const [lowerBound, upperBound] = credibleInterval
                            return (
                                <div className="font-semibold">{`[${lowerBound > 0 ? '+' : ''}${lowerBound.toFixed(
                                    2
                                )}%, ${upperBound > 0 ? '+' : ''}${upperBound.toFixed(2)}%]`}</div>
                            )
                        },
                    },
                    {
                        title: 'Win probability',
                        render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                            const { variant } = item
                            return (
                                <div className={variant === winningVariant ? 'text-success' : ''}>
                                    <b>
                                        {targetResults?.probability?.[variant] != undefined
                                            ? `${(targetResults.probability?.[variant] * 100).toFixed(1)}%`
                                            : '—'}
                                    </b>
                                </div>
                            )
                        },
                    },
                ],
            })
        } else {
            columns.push({
                title: <Header />,
                children: [
                    {
                        title: 'Conversion rate',
                        render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                            const { variant } = item
                            const conversionRate = conversionRateForVariant(targetResults || null, variant)
                            if (!conversionRate) {
                                return <>—</>
                            }
                            return <div>{`${conversionRate.toFixed(2)}%`}</div>
                        },
                    },
                    {
                        title: 'Credible interval (95%)',
                        render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                            if (item.variant === 'control') {
                                return <em>Baseline</em>
                            }

                            const credibleInterval = credibleIntervalForVariant(
                                targetResults || null,
                                item.variant,
                                metricType
                            )
                            if (!credibleInterval) {
                                return <>—</>
                            }
                            const [lowerBound, upperBound] = credibleInterval
                            return (
                                <div className="font-semibold">{`[${lowerBound > 0 ? '+' : ''}${lowerBound.toFixed(
                                    2
                                )}%, ${upperBound > 0 ? '+' : ''}${upperBound.toFixed(2)}%]`}</div>
                            )
                        },
                    },
                    {
                        title: 'Win probability',
                        render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                            const { variant } = item
                            return (
                                <div className={variant === winningVariant ? 'text-success' : ''}>
                                    <b>
                                        {targetResults?.probability?.[variant] != undefined
                                            ? `${(targetResults.probability?.[variant] * 100).toFixed(1)}%`
                                            : '—'}
                                    </b>
                                </div>
                            )
                        },
                    },
                ],
            })
        }
    })

    return (
        <>
            <div>
                <div className="flex">
                    <div className="w-1/2 pt-5">
                        <div className="inline-flex space-x-2 mb-0">
                            <h2 className="mb-0 font-semibold text-lg">Secondary metrics</h2>
                            {metrics.length > 0 && (
                                <Tooltip title="Monitor side effects of your experiment.">
                                    <IconInfo className="text-muted-alt text-base" />
                                </Tooltip>
                            )}
                        </div>
                    </div>

                    <div className="w-1/2 flex flex-col justify-end">
                        <div className="ml-auto">
                            {metrics && metrics.length > 0 && (
                                <div className="mb-2 mt-4 justify-end">
                                    <AddSecondaryMetricButton
                                        experimentId={experimentId}
                                        metrics={metrics}
                                        openEditModal={openEditModal}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                </div>
                {metrics && metrics.length > 0 ? (
                    <LemonTable
                        className="secondary-metrics-table"
                        loading={secondaryMetricResultsLoading}
                        columns={columns}
                        dataSource={tabularSecondaryMetricResults}
                        emptyState={<div>Waiting for experiment to start&hellip;</div>}
                    />
                ) : (
                    <div className="border rounded bg-bg-light pt-6 pb-8 text-muted mt-2">
                        <div className="flex flex-col items-center mx-auto space-y-3">
                            <IconAreaChart fontSize="30" />
                            <div className="text-sm text-center text-balance">
                                Add up to {MAX_SECONDARY_METRICS} secondary metrics to monitor side effects of your
                                experiment.
                            </div>
                            <AddSecondaryMetricButton
                                experimentId={experimentId}
                                metrics={metrics}
                                openEditModal={openEditModal}
                            />
                        </div>
                    </div>
                )}
            </div>
            <SecondaryMetricModal
                metricIdx={modalMetricIdx ?? 0}
                isOpen={isEditModalOpen}
                onClose={closeEditModal}
                experimentId={experimentId}
            />
            <SecondaryMetricChartModal
                experimentId={experimentId}
                metricIdx={modalMetricIdx ?? 0}
                isOpen={isChartModalOpen}
                onClose={closeChartModal}
            />
        </>
    )
}

const AddSecondaryMetricButton = ({
    experimentId,
    metrics,
    openEditModal,
}: {
    experimentId: Experiment['id']
    metrics: any
    openEditModal: (metricIdx: number) => void
}): JSX.Element => {
    const { experiment, featureFlags } = useValues(experimentLogic({ experimentId }))
    const { setExperiment } = useActions(experimentLogic({ experimentId }))
    return (
        <LemonButton
            icon={<IconPlus />}
            type="secondary"
            size="small"
            onClick={() => {
                // :FLAG: CLEAN UP AFTER MIGRATION
                if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                    const newMetricsSecondary = [...experiment.metrics_secondary, getDefaultFunnelsMetric()]
                    setExperiment({
                        metrics_secondary: newMetricsSecondary,
                    })
                    openEditModal(newMetricsSecondary.length - 1)
                } else {
                    const newSecondaryMetrics = [
                        ...experiment.secondary_metrics,
                        {
                            name: '',
                            filters: getDefaultFilters(InsightType.FUNNELS, undefined),
                        },
                    ]
                    setExperiment({
                        secondary_metrics: newSecondaryMetrics,
                    })
                    openEditModal(newSecondaryMetrics.length - 1)
                }
            }}
            disabledReason={
                metrics.length >= MAX_SECONDARY_METRICS
                    ? `You can only add up to ${MAX_SECONDARY_METRICS} secondary metrics.`
                    : undefined
            }
        >
            Add metric
        </LemonButton>
    )
}

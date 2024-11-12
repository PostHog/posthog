import { IconInfo, IconPencil, IconPlus } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSelect, LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'

import { Experiment, InsightType } from '~/types'

import {
    experimentLogic,
    getDefaultFunnelsMetric,
    getDefaultTrendsMetric,
    TabularSecondaryMetricResults,
} from '../experimentLogic'
import { SecondaryGoalFunnels } from '../SecondaryGoalFunnels'
import { SecondaryGoalTrends } from '../SecondaryGoalTrends'
import { VariantTag } from './components'

const MAX_SECONDARY_METRICS = 10

export function SecondaryMetricsModal({
    experimentId,
    metricIdx,
    isOpen,
    onClose,
}: {
    experimentId: Experiment['id']
    metricIdx: number
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const { experiment, experimentLoading, getSecondaryMetricType } = useValues(experimentLogic({ experimentId }))
    const { closeExperimentGoalModal, updateExperimentGoal, setExperiment } = useActions(
        experimentLogic({ experimentId })
    )
    const metricType = getSecondaryMetricType(metricIdx)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1000}
            title="Change secondary metric"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton form="edit-experiment-goal-form" type="secondary" onClick={closeExperimentGoalModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-goal-form"
                        onClick={() => {
                            updateExperimentGoal(experiment.filters)
                        }}
                        type="primary"
                        loading={experimentLoading}
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="flex items-center w-full gap-2 mb-4">
                <span>Metric type</span>
                <LemonSelect
                    data-attr="metrics-selector"
                    value={metricType}
                    onChange={(newMetricType) => {
                        const defaultMetric =
                            newMetricType === InsightType.TRENDS ? getDefaultTrendsMetric() : getDefaultFunnelsMetric()

                        setExperiment({
                            ...experiment,
                            metrics_secondary: [
                                ...experiment.metrics_secondary.slice(0, metricIdx),
                                defaultMetric,
                                ...experiment.metrics_secondary.slice(metricIdx + 1),
                            ],
                        })
                    }}
                    options={[
                        { value: InsightType.TRENDS, label: <b>Trends</b> },
                        { value: InsightType.FUNNELS, label: <b>Funnels</b> },
                    ]}
                />
            </div>
            {metricType === InsightType.TRENDS ? (
                <SecondaryGoalTrends metricIdx={metricIdx} />
            ) : (
                <SecondaryGoalFunnels metricIdx={metricIdx} />
            )}
        </LemonModal>
    )
}

export function SecondaryMetricsTable({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [editingMetricIdx, setEditingMetricIdx] = useState<number | null>(null)

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
        experimentMathAggregationForTrends,
        getHighestProbabilityVariant,
        featureFlags,
    } = useValues(experimentLogic({ experimentId }))
    const { setExperiment } = useActions(experimentLogic({ experimentId }))

    const openModalForMetric = (idx: number): void => {
        setEditingMetricIdx(idx)
        setIsModalOpen(true)
    }

    const closeModal = (): void => {
        setIsModalOpen(false)
        setEditingMetricIdx(null)
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
                                onClick={() => {}}
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
                                onClick={() => openModalForMetric(idx)}
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
                            return <div>{targetResults ? countDataForVariant(targetResults, variant) : '—'}</div>
                        },
                    },
                    {
                        title: 'Exposure',
                        render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                            const { variant } = item
                            return (
                                <div>{targetResults ? exposureCountDataForVariant(targetResults, variant) : '—'}</div>
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
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => {
                                            setExperiment({
                                                metrics_secondary: [
                                                    ...experiment.metrics_secondary,
                                                    getDefaultFunnelsMetric(),
                                                ],
                                            })
                                            openModalForMetric(experiment.metrics_secondary.length - 1)
                                        }}
                                        disabledReason={
                                            metrics.length >= MAX_SECONDARY_METRICS
                                                ? `You can only add up to ${MAX_SECONDARY_METRICS} secondary metrics.`
                                                : undefined
                                        }
                                    >
                                        Add metric
                                    </LemonButton>
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
                            <LemonButton
                                icon={<IconPlus />}
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    setExperiment({
                                        metrics_secondary: [...experiment.metrics_secondary, getDefaultFunnelsMetric()],
                                    })
                                    openModalForMetric(experiment.metrics_secondary.length - 1)
                                }}
                            >
                                Add metric
                            </LemonButton>
                        </div>
                    </div>
                )}
            </div>
            <SecondaryMetricsModal
                metricIdx={editingMetricIdx ?? 0}
                isOpen={isModalOpen}
                onClose={closeModal}
                experimentId={experimentId}
            />
        </>
    )
}

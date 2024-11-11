import { IconInfo, IconPencil, IconPlus } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTable, LemonTableColumns, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { useState } from 'react'

import { InsightType } from '~/types'

import { experimentLogic, TabularSecondaryMetricResults } from '../experimentLogic'
import { SecondaryGoalFunnels } from '../SecondaryGoalFunnels'
import { SecondaryGoalTrends } from '../SecondaryGoalTrends'
import { MAX_SECONDARY_METRICS, secondaryMetricsLogic, SecondaryMetricsProps } from '../secondaryMetricsLogic'
import { ResultsQuery, VariantTag } from './components'

export function SecondaryMetricsModal({
    isOpen,
    onClose,
    onMetricsChange,
    initialMetrics,
    experimentId,
    defaultAggregationType,
}: SecondaryMetricsProps & { isOpen: boolean; onClose: () => void }): JSX.Element {
    const mainLogic = experimentLogic({ experimentId })
    const logic = secondaryMetricsLogic({ onMetricsChange, initialMetrics, experimentId, defaultAggregationType })

    const { getSecondaryMetricType } = useValues(mainLogic)
    const {
        secondaryMetricModal,
        showResults,
        isSecondaryMetricModalSubmitting,
        existingModalSecondaryMetric,
        metricIdx,
    } = useValues(logic)

    const { deleteMetric, closeModal, saveSecondaryMetric } = useActions(logic)
    const { secondaryMetricResults } = useValues(experimentLogic({ experimentId }))
    const targetResults = secondaryMetricResults && secondaryMetricResults[metricIdx]

    const secondaryMetricType = getSecondaryMetricType(metricIdx)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1000}
            title={
                showResults
                    ? secondaryMetricModal.name
                    : existingModalSecondaryMetric
                    ? 'Edit secondary metric'
                    : 'New secondary metric'
            }
            footer={
                showResults ? (
                    <LemonButton form="secondary-metric-modal-form" type="secondary" onClick={closeModal}>
                        Close
                    </LemonButton>
                ) : (
                    <>
                        {existingModalSecondaryMetric && (
                            <LemonButton
                                className="mr-auto"
                                form="secondary-metric-modal-form"
                                type="secondary"
                                status="danger"
                                onClick={() => deleteMetric(metricIdx)}
                            >
                                Delete
                            </LemonButton>
                        )}
                        <div className="flex items-center gap-2">
                            <LemonButton form="secondary-metric-modal-form" type="secondary" onClick={closeModal}>
                                Cancel
                            </LemonButton>
                            <LemonButton
                                form="secondary-metric-modal-form"
                                onClick={saveSecondaryMetric}
                                type="primary"
                                loading={isSecondaryMetricModalSubmitting}
                                data-attr="create-annotation-submit"
                            >
                                {existingModalSecondaryMetric ? 'Save' : 'Create'}
                            </LemonButton>
                        </div>
                    </>
                )
            }
        >
            {showResults ? (
                <ResultsQuery targetResults={targetResults} showTable={false} />
            ) : secondaryMetricType === InsightType.TRENDS ? (
                <SecondaryGoalTrends metricIdx={metricIdx} />
            ) : (
                <SecondaryGoalFunnels metricIdx={metricIdx} />
            )}
        </LemonModal>
    )
}

export function SecondaryMetricsTable({
    onMetricsChange,
    initialMetrics,
    experimentId,
    defaultAggregationType,
}: SecondaryMetricsProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const logic = secondaryMetricsLogic({ onMetricsChange, initialMetrics, experimentId, defaultAggregationType })
    const { metrics } = useValues(logic)

    const {
        experimentResults,
        secondaryMetricResultsLoading,
        experiment,
        secondaryMetricResults,
        tabularSecondaryMetricResults,
        countDataForVariant,
        exposureCountDataForVariant,
        conversionRateForVariant,
        experimentMathAggregationForTrends,
        getHighestProbabilityVariant,
    } = useValues(experimentLogic({ experimentId }))

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

    experiment.secondary_metrics?.forEach((metric, idx) => {
        const targetResults = secondaryMetricResults?.[idx]
        const winningVariant = getHighestProbabilityVariant(targetResults || null)

        const Header = (): JSX.Element => (
            <div className="">
                <div className="flex">
                    <div className="w-3/4 truncate">{capitalizeFirstLetter(metric.name)}</div>
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
                                onClick={() => setIsModalOpen(true)}
                            />
                        </div>
                    </div>
                </div>
            </div>
        )

        if (metric.filters.insight === InsightType.TRENDS) {
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
                                        onClick={() => {}}
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
                            <LemonButton icon={<IconPlus />} type="secondary" size="small" onClick={() => {}}>
                                Add metric
                            </LemonButton>
                        </div>
                    </div>
                )}
            </div>
            <SecondaryMetricsModal
                isOpen={isModalOpen}
                onClose={() => setIsModalOpen(false)}
                onMetricsChange={onMetricsChange}
                initialMetrics={initialMetrics}
                experimentId={experimentId}
                defaultAggregationType={defaultAggregationType}
            />
        </>
    )
}

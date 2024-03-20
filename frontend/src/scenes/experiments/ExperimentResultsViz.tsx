import './Experiment.scss'

import { IconInfo, IconPencil, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonTable,
    LemonTableColumns,
    LemonTag,
    LemonTagType,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import { Empty } from 'antd'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { AnimationType } from 'lib/animations/animations'
import { getSeriesColor } from 'lib/colors'
import { Animation } from 'lib/components/Animation/Animation'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'
import { useEffect, useState } from 'react'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import {
    ActionFilter as ActionFilterType,
    AnyPropertyFilter,
    Experiment,
    FeatureFlagGroupType,
    FilterType,
    FunnelExperimentVariant,
    FunnelStep,
    InsightShortId,
    InsightType,
    MultivariateFlagVariant,
    TrendExperimentVariant,
} from '~/types'

import { EXPERIMENT_EXPOSURE_INSIGHT_ID, EXPERIMENT_INSIGHT_ID, SECONDARY_METRIC_INSIGHT_ID } from './constants'
import { ResetButton } from './Experiment'
import { experimentLogic, TabularSecondaryMetricResults } from './experimentLogic'
import { MetricSelector } from './MetricSelector'
import { secondaryMetricsLogic, SecondaryMetricsProps } from './secondaryMetricsLogic'
import { getExperimentInsightColour, transformResultFilters } from './utils'

export function ExperimentStatus(): JSX.Element {
    const {
        experimentResults,
        getIndexForVariant,
        experimentInsightType,
        sortedConversionRates,
        highestProbabilityVariant,
        areResultsSignificant,
    } = useValues(experimentLogic)

    function SignificanceText(): JSX.Element {
        return (
            <>
                <span>Your results are&nbsp;</span>
                <span className="font-semibold">{`${areResultsSignificant ? 'significant' : 'not significant'}`}.</span>
            </>
        )
    }

    if (experimentInsightType === InsightType.FUNNELS) {
        const winningVariant = sortedConversionRates[0]
        const secondBestVariant = sortedConversionRates[1]
        const difference = winningVariant.conversionRate - secondBestVariant.conversionRate

        return (
            <div>
                <h2 className="font-semibold text-lg">Status</h2>
                <LemonDivider />
                <div className="items-center inline-flex">
                    <div
                        className="w-2 h-2 rounded-full mr-1"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ backgroundColor: getSeriesColor(winningVariant.index + 1) }}
                    />
                    <span className="font-semibold">{capitalizeFirstLetter(winningVariant.key)}</span>
                    <span>&nbsp;is winning with a&nbsp;</span>
                    <span className="font-semibold text-success items-center">{`${difference}% lift`}</span>
                    <span>&nbsp;in conversion rate (vs&nbsp;</span>
                    <div
                        className="w-2 h-2 rounded-full mr-1"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            backgroundColor: getSeriesColor(secondBestVariant.index + 1),
                        }}
                    />
                    <span className="font-semibold">{capitalizeFirstLetter(secondBestVariant.key)}</span>
                    <span>).&nbsp;</span>
                    <SignificanceText />
                </div>
            </div>
        )
    }

    const index = getIndexForVariant(experimentResults, highestProbabilityVariant || '')
    if (highestProbabilityVariant && index !== null && experimentResults) {
        const { probability } = experimentResults

        return (
            <div>
                <h2 className="font-semibold text-lg">Status</h2>
                <LemonDivider />
                <div className="items-center inline-flex">
                    <div
                        className="w-2 h-2 rounded-full mr-1"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            backgroundColor: getSeriesColor(index + 2),
                        }}
                    />
                    <span className="font-semibold">{capitalizeFirstLetter(highestProbabilityVariant)}</span>
                    <span>&nbsp;is winning with a&nbsp;</span>
                    <span className="font-semibold text-success items-center">
                        {`${(probability[highestProbabilityVariant] * 100).toFixed(2)}% probability`}&nbsp;
                    </span>
                    <span>of being best.&nbsp;</span>
                    <SignificanceText />
                </div>
            </div>
        )
    }

    return <></>
}

export function ExperimentProgressBar(): JSX.Element {
    const { experiment, experimentResults, experimentInsightType } = useValues(experimentLogic)

    // Parameters for experiment results
    // don't use creation variables in results
    const funnelResultsPersonsTotal =
        experimentInsightType === InsightType.FUNNELS && experimentResults?.insight
            ? (experimentResults.insight as FunnelStep[][]).reduce(
                  (sum: number, variantResult: FunnelStep[]) => variantResult[0]?.count + sum,
                  0
              )
            : 0

    const experimentProgressPercent =
        experimentInsightType === InsightType.FUNNELS
            ? ((funnelResultsPersonsTotal || 0) / (experiment?.parameters?.recommended_sample_size || 1)) * 100
            : (dayjs().diff(experiment?.start_date, 'day') / (experiment?.parameters?.recommended_running_time || 1)) *
              100

    return (
        <div>
            <div className="mb-1 font-semibold">{`${
                experimentProgressPercent > 100 ? 100 : experimentProgressPercent
            }% complete`}</div>
            <LemonProgress
                className="w-full border"
                bgColor="var(--bg-table)"
                size="large"
                percent={experimentProgressPercent}
            />
            {experimentInsightType === InsightType.TRENDS && experiment.start_date && (
                <div className="flex justify-between mt-2">
                    {experiment.end_date ? (
                        <div>
                            Ran for <b>{dayjs(experiment.end_date).diff(experiment.start_date, 'day')}</b> days
                        </div>
                    ) : (
                        <div>
                            <b>{dayjs().diff(experiment.start_date, 'day')}</b> days running
                        </div>
                    )}
                    <div>
                        Goal: <b>{experiment?.parameters?.recommended_running_time ?? 'Unknown'}</b> days
                    </div>
                </div>
            )}
            {experimentInsightType === InsightType.FUNNELS && (
                <div className="flex justify-between mt-2">
                    {experiment.end_date ? (
                        <div>
                            Saw <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b> participants
                        </div>
                    ) : (
                        <div>
                            <b>{humanFriendlyNumber(funnelResultsPersonsTotal)}</b> participants seen
                        </div>
                    )}
                    <div>
                        Goal: <b>{humanFriendlyNumber(experiment?.parameters?.recommended_sample_size || 0)}</b>{' '}
                        participants
                    </div>
                </div>
            )}
        </div>
    )
}

export function SummaryTable(): JSX.Element {
    const {
        experimentResults,
        experimentInsightType,
        exposureCountDataForVariant,
        conversionRateForVariant,
        sortedConversionRates,
        experimentMathAggregationForTrends,
        countDataForVariant,
        areTrendResultsConfusing,
    } = useValues(experimentLogic)

    if (!experimentResults) {
        return <></>
    }

    const columns: LemonTableColumns<TrendExperimentVariant | FunnelExperimentVariant> = [
        {
            key: 'variants',
            title: 'Variant',
            render: function Key(_, item, index): JSX.Element {
                return (
                    <div className="flex items-center">
                        <div
                            className="w-2 h-2 rounded-full mr-2"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: getSeriesColor(index + 1) }}
                        />
                        <span className="font-semibold">{capitalizeFirstLetter(item.key)}</span>
                    </div>
                )
            },
        },
    ]

    if (experimentInsightType === InsightType.TRENDS) {
        columns.push({
            key: 'counts',
            title: (
                <div className="flex">
                    {experimentResults.insight?.[0] && 'action' in experimentResults.insight[0] && (
                        <EntityFilterInfo filter={experimentResults.insight[0].action} />
                    )}
                    <span className="pl-1">
                        {experimentMathAggregationForTrends(experimentResults?.filters) ? 'metric' : 'count'}
                    </span>
                </div>
            ),
            render: function Key(_, item, index): JSX.Element {
                return (
                    <div className="flex">
                        {countDataForVariant(experimentResults, item.key)}{' '}
                        {areTrendResultsConfusing && index === 0 && (
                            <Tooltip
                                placement="right"
                                title="It might seem confusing that the best variant has lower absolute count, but this can happen when fewer people are exposed to this variant, so its relative count is higher."
                            >
                                <IconInfo className="py-1 px-0.5" />
                            </Tooltip>
                        )}
                    </div>
                )
            },
        })
        columns.push({
            key: 'exposure',
            title: 'Exposure',
            render: function Key(_, item): JSX.Element {
                return <div>{exposureCountDataForVariant(experimentResults, item.key)}</div>
            },
        })
    }

    if (experimentInsightType === InsightType.FUNNELS) {
        columns.push({
            key: 'conversionRate',
            title: 'Conversion rate',
            render: function Key(_, item): JSX.Element {
                const isWinning = item.key === sortedConversionRates[0].key
                return (
                    <div className={`font-semibold ${isWinning && 'text-success'}`}>{`${conversionRateForVariant(
                        experimentResults,
                        item.key
                    )}%`}</div>
                )
            },
        })
    }

    columns.push({
        key: 'winProbability',
        title: 'Win probability',
        render: function Key(_, item): JSX.Element {
            const percentage =
                experimentResults?.probability?.[item.key] != undefined &&
                experimentResults.probability?.[item.key] * 100

            return (
                <>
                    {percentage ? (
                        <span className="inline-flex items-center w-30 space-x-4">
                            <LemonProgress className="inline-flex w-3/4" percent={percentage} />
                            <span className="w-1/4">{percentage.toFixed(2)}%</span>
                        </span>
                    ) : (
                        '--'
                    )}
                </>
            )
        },
    })

    return (
        <div className="mb-4">
            <LemonTable loading={false} columns={columns} dataSource={experimentResults?.variants || []} />
        </div>
    )
}

export function ExperimentGoal(): JSX.Element {
    const { experiment, experimentId, experimentInsightType, experimentMathAggregationForTrends } =
        useValues(experimentLogic)
    const { openExperimentGoalModal } = useActions(experimentLogic({ experimentId }))

    return (
        <div>
            <h2 className="font-semibold text-lg mb-1">Experiment goal</h2>
            <div>
                This <b>{experimentInsightType === InsightType.FUNNELS ? 'funnel' : 'trend'}</b>{' '}
                {experimentInsightType === InsightType.FUNNELS
                    ? 'experiment measures conversion through each step of the user journey.'
                    : 'experiment tracks the performance of a single metric.'}
            </div>
            <div className="inline-flex space-x-6">
                <div>
                    <div className="card-secondary mb-2 mt-4">
                        {experimentInsightType === InsightType.FUNNELS ? 'Conversion goal steps' : 'Trend goal'}
                    </div>
                    <MetricDisplay filters={experiment.filters} />
                    <LemonButton size="small" type="secondary" onClick={openExperimentGoalModal}>
                        Change experiment goal
                    </LemonButton>
                </div>
                {experimentInsightType === InsightType.TRENDS &&
                    !experimentMathAggregationForTrends(experiment.filters) && (
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
        </div>
    )
}

export function Results(): JSX.Element {
    const { experimentResults } = useValues(experimentLogic)

    return (
        <div>
            <div className="inline-flex items-center space-x-2 mb-2">
                <h2 className="m-0 font-semibold text-lg">Results</h2>
                <ResultsTag />
            </div>
            <SummaryTable />
            <Query
                query={{
                    kind: NodeKind.InsightVizNode,
                    source: filtersToQueryNode(transformResultFilters(experimentResults?.filters ?? {})),
                    showTable: true,
                    showLastComputation: true,
                    showLastComputationRefresh: false,
                }}
                context={{
                    insightProps: {
                        dashboardItemId: experimentResults?.fakeInsightId as InsightShortId,
                        cachedInsight: {
                            short_id: experimentResults?.fakeInsightId as InsightShortId,
                            filters: transformResultFilters(experimentResults?.filters ?? {}),
                            result: experimentResults?.insight,
                            disable_baseline: true,
                            last_refresh: experimentResults?.last_refresh,
                        },
                        doNotLoad: true,
                    },
                }}
                readOnly
            />
        </div>
    )
}

export function SecondaryMetricsTable({
    onMetricsChange,
    initialMetrics,
    experimentId,
    defaultAggregationType,
}: SecondaryMetricsProps): JSX.Element {
    const logic = secondaryMetricsLogic({ onMetricsChange, initialMetrics, experimentId, defaultAggregationType })
    const { metrics, isModalOpen, isSecondaryMetricModalSubmitting, existingModalSecondaryMetric, metricIdx } =
        useValues(logic)

    const {
        deleteMetric,
        openModalToCreateSecondaryMetric,
        openModalToEditSecondaryMetric,
        closeModal,
        saveSecondaryMetric,
        setPreviewInsight,
    } = useActions(logic)

    const {
        secondaryMetricResultsLoading,
        isExperimentRunning,
        getIndexForVariant,
        experiment,
        experimentResults,
        editingExistingExperiment,
        tabularSecondaryMetricResults,
    } = useValues(experimentLogic({ experimentId }))

    const columns: LemonTableColumns<TabularSecondaryMetricResults> = [
        {
            key: 'variant',
            title: 'Variant',
            render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                return (
                    <div className="flex items-center">
                        <div
                            className="w-2 h-2 rounded-full mr-2"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                backgroundColor: getExperimentInsightColour(
                                    getIndexForVariant(experimentResults, item.variant)
                                ),
                            }}
                        />
                        <span className="font-semibold">{capitalizeFirstLetter(item.variant)}</span>
                    </div>
                )
            },
        },
    ]

    experiment.secondary_metrics?.forEach((metric, idx) => {
        columns.push({
            key: `results_${idx}`,
            title: (
                <span className="inline-flex py-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconAreaChart />}
                        onClick={() => openModalToEditSecondaryMetric(metric, idx)}
                    >
                        <b>{capitalizeFirstLetter(metric.name)}</b>
                    </LemonButton>
                </span>
            ),
            render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                return (
                    <div>
                        {item.results?.[idx].result ? (
                            item.results[idx].insightType === InsightType.FUNNELS ? (
                                <>{((item.results[idx].result as number) * 100).toFixed(1)}%</>
                            ) : (
                                <>{humanFriendlyNumber(item.results[idx].result as number)}</>
                            )
                        ) : (
                            <>--</>
                        )}
                    </div>
                )
            },
        })
    })

    return (
        <>
            <LemonModal
                isOpen={isModalOpen}
                onClose={closeModal}
                width={1000}
                title={existingModalSecondaryMetric ? 'Edit secondary metric' : 'New secondary metric'}
                footer={
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
                }
            >
                <Form
                    logic={secondaryMetricsLogic}
                    props={{ onMetricsChange, initialMetrics, experimentId, defaultAggregationType }}
                    formKey="secondaryMetricModal"
                    id="secondary-metric-modal-form"
                    className="space-y-4"
                >
                    <LemonField name="name" label="Name">
                        <LemonInput data-attr="secondary-metric-name" />
                    </LemonField>
                    <LemonField name="filters" label="Query">
                        <MetricSelector
                            dashboardItemId={SECONDARY_METRIC_INSIGHT_ID}
                            setPreviewInsight={setPreviewInsight}
                            showDateRangeBanner={isExperimentRunning}
                        />
                    </LemonField>
                </Form>
            </LemonModal>
            {experimentId == 'new' || editingExistingExperiment ? (
                <div className="flex">
                    <div>
                        {metrics.map((metric, idx) => (
                            <div key={idx} className="mt-4 border rounded p-4">
                                <div className="flex items-center justify-between w-full mb-3 pb-2 border-b">
                                    <div>
                                        <b>{metric.name}</b>
                                    </div>
                                    <div className="flex">
                                        <LemonButton
                                            icon={<IconPencil />}
                                            size="small"
                                            onClick={() => openModalToEditSecondaryMetric(metric, idx)}
                                        />
                                        <LemonButton
                                            icon={<IconTrash />}
                                            size="small"
                                            onClick={() => deleteMetric(idx)}
                                        />
                                    </div>
                                </div>
                                {metric.filters.insight === InsightType.FUNNELS && (
                                    <ActionFilter
                                        bordered
                                        filters={metric.filters}
                                        setFilters={() => {}}
                                        typeKey={`funnel-preview-${idx}`}
                                        mathAvailability={MathAvailability.None}
                                        buttonCopy="Add funnel step"
                                        seriesIndicatorType="numeric"
                                        sortable
                                        showNestedArrow
                                        propertiesTaxonomicGroupTypes={[
                                            TaxonomicFilterGroupType.EventProperties,
                                            TaxonomicFilterGroupType.PersonProperties,
                                            TaxonomicFilterGroupType.EventFeatureFlags,
                                            TaxonomicFilterGroupType.Cohorts,
                                            TaxonomicFilterGroupType.Elements,
                                        ]}
                                        readOnly
                                    />
                                )}
                                {metric.filters.insight === InsightType.TRENDS && (
                                    <ActionFilter
                                        bordered
                                        filters={metric.filters}
                                        setFilters={() => {}}
                                        typeKey={`trend-preview-${idx}`}
                                        buttonCopy="Add graph series"
                                        showSeriesIndicator
                                        entitiesLimit={1}
                                        propertiesTaxonomicGroupTypes={[
                                            TaxonomicFilterGroupType.EventProperties,
                                            TaxonomicFilterGroupType.PersonProperties,
                                            TaxonomicFilterGroupType.EventFeatureFlags,
                                            TaxonomicFilterGroupType.Cohorts,
                                            TaxonomicFilterGroupType.Elements,
                                        ]}
                                        readOnly={true}
                                    />
                                )}
                            </div>
                        ))}
                        {metrics && !(metrics.length > 2) && (
                            <div className="mb-2 mt-4">
                                <LemonButton
                                    data-attr="add-secondary-metric-btn"
                                    type="secondary"
                                    onClick={openModalToCreateSecondaryMetric}
                                >
                                    Add metric
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </div>
            ) : (
                <div>
                    <div className="flex">
                        <div className="w-1/2">
                            <h2 className="mb-0 font-semibold text-lg">Secondary metrics</h2>
                            <div className="mb-2">Click a metric name to compare variants on a graph.</div>
                        </div>

                        <div className="w-1/2 flex flex-col justify-end">
                            <div className="ml-auto">
                                {metrics && !(metrics.length > 2) && isExperimentRunning && (
                                    <div className="mb-2 mt-4 justify-end">
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={openModalToCreateSecondaryMetric}
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
                            loading={secondaryMetricResultsLoading}
                            columns={columns}
                            dataSource={tabularSecondaryMetricResults}
                        />
                    ) : !isExperimentRunning ? (
                        <>--</>
                    ) : (
                        <></>
                    )}
                </div>
            )}
        </>
    )
}

export function DistributionTable(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    const columns: LemonTableColumns<MultivariateFlagVariant> = [
        {
            className: 'w-1/3',
            key: 'key',
            title: 'Variant',
            render: function Key(_, item, index): JSX.Element {
                return (
                    <div className="flex items-center">
                        <div
                            className="w-2 h-2 rounded-full mr-2"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: getSeriesColor(index + 1) }}
                        />
                        <span className="font-semibold">{capitalizeFirstLetter(item.key)}</span>
                    </div>
                )
            },
        },
        {
            className: 'w-1/3',
            key: 'rollout_percentage',
            title: 'Rollout',
            render: function Key(_, item): JSX.Element {
                return <div>{`${item.rollout_percentage}%`}</div>
            },
        },
    ]

    return (
        <div>
            <div className="flex">
                <div className="w-1/2">
                    <h2 className="font-semibold text-lg">Distribution</h2>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto mb-2">
                        <Link
                            target="_blank"
                            className="font-semibold"
                            to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                        >
                            Manage distribution
                        </Link>
                    </div>
                </div>
            </div>
            <LemonTable loading={false} columns={columns} dataSource={experiment.parameters.feature_flag_variants} />
        </div>
    )
}

export function ReleaseConditionsTable(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const columns: LemonTableColumns<FeatureFlagGroupType> = [
        {
            className: 'w-1/3',
            key: 'key',
            title: '',
            render: function Key(_, item, index): JSX.Element {
                return <div className="font-semibold">{`Set ${index + 1}`}</div>
            },
        },
        {
            className: 'w-1/3',
            key: 'rollout_percentage',
            title: 'Rollout',
            render: function Key(_, item): JSX.Element {
                const aggregationTargetName =
                    experiment.filters.aggregation_group_type_index != null
                        ? aggregationLabel(experiment.filters.aggregation_group_type_index).plural
                        : 'users'

                const releaseText = `${item.rollout_percentage}% of ${aggregationTargetName}`

                return (
                    <div>
                        {releaseText.startsWith('100% of') ? (
                            <LemonTag type="highlight">{releaseText}</LemonTag>
                        ) : (
                            releaseText
                        )}
                    </div>
                )
            },
        },
        {
            className: 'w-1/3',
            key: 'variant',
            title: 'Override',
            render: function Key(_, item): JSX.Element {
                return <div>{item.variant || '--'}</div>
            },
        },
    ]

    return (
        <div>
            <div className="flex">
                <div className="w-1/2">
                    <h2 className="font-semibold text-lg">Release conditions</h2>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto mb-2">
                        <Link
                            target="_blank"
                            className="font-semibold"
                            to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                        >
                            Manage release conditions
                        </Link>
                    </div>
                </div>
            </div>
            <LemonTable loading={false} columns={columns} dataSource={experiment.feature_flag?.filters.groups || []} />
        </div>
    )
}

export function NoResultsEmptyState(): JSX.Element {
    const { experimentResultsLoading, experimentResultCalculationError } = useValues(experimentLogic)

    if (experimentResultsLoading) {
        return <></>
    }

    return (
        <div>
            <h2 className="font-semibold text-lg">Results</h2>
            <div className="border rounded bg-bg-light pt-6 pb-8 text-muted">
                <div className="flex flex-col items-center mx-auto">
                    <Empty className="my-4" image={Empty.PRESENTED_IMAGE_SIMPLE} description="" />
                    <h2 className="text-xl font-semibold leading-tight">There are no experiment results yet</h2>
                    {!!experimentResultCalculationError && (
                        <div className="text-sm text-center text-balance">{experimentResultCalculationError}</div>
                    )}
                    <div className="text-sm text-center text-balance">
                        Wait a bit longer for your users to be exposed to the experiment. Double check your feature flag
                        implementation if you're still not seeing results.
                    </div>
                </div>
            </div>
        </div>
    )
}

export function ExposureMetric({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment } = useValues(experimentLogic({ experimentId }))
    const { openExperimentExposureModal, updateExperimentExposure } = useActions(experimentLogic({ experimentId }))

    return (
        <>
            <div className="card-secondary mb-2 mt-4">
                Exposure metric
                <Tooltip
                    title={`This metric determines how we calculate exposure for the experiment. Only users who have this event alongside the property '$feature/${experiment.feature_flag_key}' are included in the exposure calculations.`}
                >
                    <IconInfo className="ml-1 text-muted text-sm" />
                </Tooltip>
            </div>
            {experiment.parameters?.custom_exposure_filter ? (
                <MetricDisplay filters={experiment.parameters.custom_exposure_filter} />
            ) : (
                <span className="description">Default via $feature_flag_called events</span>
            )}
            <div className="mb-2 mt-2">
                <span className="flex">
                    <LemonButton type="secondary" size="small" onClick={openExperimentExposureModal} className="mr-2">
                        Change exposure metric
                    </LemonButton>
                    {experiment.parameters?.custom_exposure_filter && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            size="small"
                            onClick={() => updateExperimentExposure(null)}
                        >
                            Reset exposure
                        </LemonButton>
                    )}
                </span>
            </div>
        </>
    )
}

export function ExperimentGoalModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, isExperimentGoalModalOpen, experimentLoading } = useValues(experimentLogic({ experimentId }))
    const { closeExperimentGoalModal, updateExperimentGoal, setNewExperimentInsight } = useActions(
        experimentLogic({ experimentId })
    )

    return (
        <LemonModal
            isOpen={isExperimentGoalModalOpen}
            onClose={closeExperimentGoalModal}
            width={1000}
            title="Change experiment goal"
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
            <Form
                logic={experimentLogic}
                props={{ experimentId }}
                formKey="experiment"
                id="edit-experiment-goal-form"
                className="space-y-4"
            >
                <Field name="filters">
                    <MetricSelector
                        dashboardItemId={EXPERIMENT_INSIGHT_ID}
                        setPreviewInsight={setNewExperimentInsight}
                        showDateRangeBanner
                    />
                </Field>
            </Form>
        </LemonModal>
    )
}

export function ExperimentExposureModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, isExperimentExposureModalOpen, experimentLoading } = useValues(
        experimentLogic({ experimentId })
    )
    const { closeExperimentExposureModal, updateExperimentExposure, setExperimentExposureInsight } = useActions(
        experimentLogic({ experimentId })
    )

    return (
        <LemonModal
            isOpen={isExperimentExposureModalOpen}
            onClose={closeExperimentExposureModal}
            width={1000}
            title="Change experiment exposure"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        type="secondary"
                        onClick={closeExperimentExposureModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => {
                            if (experiment.parameters.custom_exposure_filter) {
                                updateExperimentExposure(experiment.parameters.custom_exposure_filter)
                            }
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
            <Form
                logic={experimentLogic}
                props={{ experimentId }}
                formKey="experiment"
                id="edit-experiment-exposure-form"
                className="space-y-4"
            >
                <Field name="filters">
                    <MetricSelector
                        dashboardItemId={EXPERIMENT_EXPOSURE_INSIGHT_ID}
                        setPreviewInsight={setExperimentExposureInsight}
                    />
                </Field>
            </Form>
        </LemonModal>
    )
}

export function ExperimentActiveBanner(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    const { resetRunningExperiment, endExperiment } = useActions(experimentLogic)

    return (
        <LemonBanner type="info">
            <div className="flex">
                <div className="w-1/2 flex items-center">
                    This experiment is <b>&nbsp;active.</b>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto inline-flex space-x-2">
                        <ResetButton experiment={experiment} onConfirm={resetRunningExperiment} />
                        <LemonButton type="secondary" status="danger" onClick={() => endExperiment()}>
                            Stop
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonBanner>
    )
}

export function ExperimentDraftBanner(): JSX.Element {
    const { launchExperiment, setEditExperiment } = useActions(experimentLogic)

    return (
        <LemonBanner type="info">
            <div className="flex">
                <div className="w-1/2 flex items-center">
                    This experiment is <b>&nbsp;draft.</b>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto inline-flex space-x-2">
                        <LemonButton type="secondary" onClick={() => setEditExperiment(true)}>
                            Edit
                        </LemonButton>
                        <LemonButton type="primary" onClick={() => launchExperiment()}>
                            Launch
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonBanner>
    )
}

export function ExperimentStoppedBanner(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { archiveExperiment, resetRunningExperiment } = useActions(experimentLogic)

    return (
        <LemonBanner type="info">
            <div className="flex">
                <div className="w-1/2 flex items-center">
                    This experiment has been <b>&nbsp;stopped.</b>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto inline-flex space-x-2">
                        <ResetButton experiment={experiment} onConfirm={resetRunningExperiment} />
                        <LemonButton type="secondary" status="danger" onClick={() => archiveExperiment()}>
                            <b>Archive</b>
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonBanner>
    )
}

export function ExperimentLoader(): JSX.Element {
    return (
        <LemonTable
            dataSource={[]}
            columns={[
                {
                    title: '',
                    dataIndex: '',
                },
            ]}
            loadingSkeletonRows={8}
            loading={true}
        />
    )
}

export function MetricDisplay({ filters }: { filters?: FilterType }): JSX.Element {
    const experimentInsightType = filters?.insight || InsightType.TRENDS

    return (
        <>
            {([...(filters?.events || []), ...(filters?.actions || [])] as ActionFilterType[])
                .sort((a, b) => (a.order || 0) - (b.order || 0))
                .map((event: ActionFilterType, idx: number) => (
                    <div key={idx} className="mb-2">
                        <div className="flex mb-1">
                            <div
                                className="shrink-0 w-6 h-6 mr-2 font-bold text-center text-primary-alt border rounded"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ backgroundColor: 'var(--bg-table)' }}
                            >
                                {experimentInsightType === InsightType.FUNNELS ? (event.order || 0) + 1 : idx + 1}
                            </div>
                            <b>
                                <InsightLabel
                                    action={event}
                                    showCountedByTag={experimentInsightType === InsightType.TRENDS}
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

export function EllipsisAnimation(): JSX.Element {
    const [ellipsis, setEllipsis] = useState('.')

    useEffect(() => {
        let count = 1
        let direction = 1

        const interval = setInterval(() => {
            setEllipsis('.'.repeat(count))
            count += direction

            if (count === 3 || count === 1) {
                direction *= -1
            }
        }, 300)

        return () => clearInterval(interval)
    }, [])

    return <span>{ellipsis}</span>
}

export function ExperimentLoadingAnimation(): JSX.Element {
    function EllipsisAnimation(): JSX.Element {
        const [ellipsis, setEllipsis] = useState('.')

        useEffect(() => {
            let count = 1
            let direction = 1

            const interval = setInterval(() => {
                setEllipsis('.'.repeat(count))
                count += direction

                if (count === 3 || count === 1) {
                    direction *= -1
                }
            }, 300)

            return () => clearInterval(interval)
        }, [])

        return <span>{ellipsis}</span>
    }

    return (
        <div className="flex flex-col flex-1 justify-center items-center">
            <Animation type={AnimationType.LaptopHog} />
            <div className="text-xs text-muted w-44">
                <span className="mr-1">Fetching experiment results</span>
                <EllipsisAnimation />
            </div>
        </div>
    )
}

export function PageHeaderCustom(): JSX.Element {
    const { experiment, isExperimentRunning } = useValues(experimentLogic)
    const { launchExperiment, setEditExperiment, loadExperimentResults, loadSecondaryMetricResults } =
        useActions(experimentLogic)

    return (
        <PageHeader
            buttons={
                <>
                    <div className="flex flex-row gap-2">
                        <>
                            <More
                                overlay={
                                    <>
                                        {experiment && !isExperimentRunning && (
                                            <>
                                                <LemonButton fullWidth onClick={() => setEditExperiment(true)}>
                                                    Edit
                                                </LemonButton>
                                                <LemonButton fullWidth onClick={() => launchExperiment()}>
                                                    Launch
                                                </LemonButton>
                                            </>
                                        )}
                                        {experiment && isExperimentRunning && (
                                            <>
                                                <LemonButton
                                                    onClick={() => loadExperimentResults(true)}
                                                    fullWidth
                                                    data-attr="refresh-experiment"
                                                >
                                                    Refresh experiment results
                                                </LemonButton>
                                                <LemonButton
                                                    onClick={() => loadSecondaryMetricResults(true)}
                                                    fullWidth
                                                    data-attr="refresh-secondary-metrics"
                                                >
                                                    Refresh secondary metrics
                                                </LemonButton>
                                            </>
                                        )}
                                    </>
                                }
                            />
                        </>
                    </div>
                </>
            }
        />
    )
}

export function ResultsTag(): JSX.Element {
    const { areResultsSignificant } = useValues(experimentLogic)
    const result: { color: LemonTagType; label: string } = areResultsSignificant
        ? { color: 'success', label: 'Significant' }
        : { color: 'primary', label: 'Not significant' }

    return (
        <LemonTag type={result.color}>
            <b className="uppercase">{result.label}</b>
        </LemonTag>
    )
}

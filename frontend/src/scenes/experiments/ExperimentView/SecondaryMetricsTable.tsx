import '../Experiment.scss'

import { IconPencil, IconPlus } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { capitalizeFirstLetter } from 'lib/utils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { Query } from '~/queries/Query/Query'
import { InsightType } from '~/types'

import { SECONDARY_METRIC_INSIGHT_ID } from '../constants'
import { experimentLogic, TabularSecondaryMetricResults } from '../experimentLogic'
import { ExperimentInsightCreator, MetricSelector } from '../MetricSelector'
import { secondaryMetricsLogic, SecondaryMetricsProps } from '../secondaryMetricsLogic'
import { findKeyWithHighestNumber, getExperimentInsightColour } from '../utils'

export function SecondaryMetricsModal({
    onMetricsChange,
    initialMetrics,
    experimentId,
    defaultAggregationType,
}: SecondaryMetricsProps): JSX.Element {
    const logic = secondaryMetricsLogic({ onMetricsChange, initialMetrics, experimentId, defaultAggregationType })
    const {
        secondaryMetricModal,
        isModalOpen,
        isModalReadOnly,
        isSecondaryMetricModalSubmitting,
        existingModalSecondaryMetric,
        metricIdx,
    } = useValues(logic)

    const { deleteMetric, closeModal, saveSecondaryMetric, setPreviewInsight } = useActions(logic)

    const { isExperimentRunning } = useValues(experimentLogic({ experimentId }))

    const insightLogicInstance = insightLogic({ dashboardItemId: SECONDARY_METRIC_INSIGHT_ID, syncWithUrl: false })
    const { insightProps } = useValues(insightLogicInstance)
    const { query } = useValues(insightDataLogic(insightProps))

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            width={1000}
            title={
                isModalReadOnly
                    ? secondaryMetricModal.name
                    : existingModalSecondaryMetric
                    ? 'Edit secondary metric'
                    : 'New secondary metric'
            }
            footer={
                isModalReadOnly ? (
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
            {isModalReadOnly ? (
                <div>
                    <ExperimentInsightCreator insightProps={insightProps} />
                    {isExperimentRunning && (
                        <LemonBanner type="info" className="mt-3 mb-3">
                            Preview insights are generated based on {EXPERIMENT_DEFAULT_DURATION} days of data. This can
                            cause a mismatch between the preview and the actual results.
                        </LemonBanner>
                    )}
                    <BindLogic logic={insightLogic} props={insightProps}>
                        <Query query={query} context={{ insightProps }} readOnly />
                    </BindLogic>
                </div>
            ) : (
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
    const logic = secondaryMetricsLogic({ onMetricsChange, initialMetrics, experimentId, defaultAggregationType })
    const { metrics } = useValues(logic)

    const { openModalToCreateSecondaryMetric, openModalToEditSecondaryMetric } = useActions(logic)

    const {
        secondaryMetricResultsLoading,
        isExperimentRunning,
        getIndexForVariant,
        experiment,
        experimentResults,
        secondaryMetricResults,
        tabularSecondaryMetricResults,
        countDataForVariant,
        exposureCountDataForVariant,
        conversionRateForVariant,
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
        const Header = (): JSX.Element => (
            <div className="py-4 px-2 border-l border-r border-b">
                <div className="flex">
                    <div className="w-3/4 truncate">{capitalizeFirstLetter(metric.name)}</div>
                    <div className="w-1/4 flex flex-col justify-end">
                        <div className="ml-auto space-x-2 pb-1 inline-flex">
                            <LemonButton
                                className="max-w-72"
                                type="secondary"
                                size="xsmall"
                                icon={<IconAreaChart />}
                                onClick={() => openModalToEditSecondaryMetric(metric, idx, true)}
                            />
                            <LemonButton
                                className="max-w-72"
                                type="secondary"
                                size="xsmall"
                                icon={<IconPencil />}
                                onClick={() => openModalToEditSecondaryMetric(metric, idx, false)}
                            />
                        </div>
                    </div>
                </div>
            </div>
        )

        if (metric.filters.insight === InsightType.TRENDS) {
            columns.push({
                key: `results_${idx}`,
                title: (
                    <div className="w-80">
                        <Header />
                        <div className="w-80 inline-flex">
                            <div className="w-1/3 py-1 flex items-center justify-center border-l text-xs">Count</div>
                            <div className="w-1/3 py-1 flex items-center justify-center border-l text-xs">Exposure</div>
                            <div className="w-1/3 py-1 flex items-center justify-center text-center border-l border-r text-xs text-wrap">
                                Win probability
                            </div>
                        </div>
                    </div>
                ),
                render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                    const targetResults = secondaryMetricResults?.[idx]

                    const { variant } = item
                    const winningVariant = findKeyWithHighestNumber(targetResults?.probability || null)

                    return (
                        <div className="w-80 py-0 inline-flex">
                            <div className="w-1/3 leading-10 text-center border-l text-xs">
                                {targetResults ? countDataForVariant(targetResults, variant) : '--'}
                            </div>
                            <div className="w-1/3 leading-10 text-center border-l text-xs">
                                {targetResults ? exposureCountDataForVariant(targetResults, variant) : '--'}
                            </div>
                            <div
                                className={`w-1/3 leading-10 text-center border-l border-r text-xs ${
                                    variant === winningVariant ? 'text-success' : ''
                                }`}
                            >
                                <b>
                                    {targetResults?.probability?.[variant] != undefined
                                        ? `${(targetResults.probability?.[variant] * 100).toFixed(1)}%`
                                        : '--'}
                                </b>
                            </div>
                        </div>
                    )
                },
            })
        } else {
            columns.push({
                key: `results_${idx}`,
                title: (
                    <div className="w-80">
                        <Header />
                        <div className="w-80 inline-flex">
                            <div className="w-1/2 py-3 flex items-center justify-center border-l text-xs">
                                Conversion rate
                            </div>
                            <div className="w-1/2 py-3 flex items-center justify-center text-center border-l border-r text-xs text-wrap">
                                Win probability
                            </div>
                        </div>
                    </div>
                ),
                render: function Key(_, item: TabularSecondaryMetricResults): JSX.Element {
                    const targetResults = secondaryMetricResults?.[idx]

                    const { variant } = item
                    const winningVariant = findKeyWithHighestNumber(targetResults?.probability || null)

                    const conversionRate = conversionRateForVariant(targetResults || null, variant)
                    return (
                        <div className="w-80 h-10 py-0 inline-flex">
                            <div className="w-1/2 leading-10 text-center border-l text-xs">
                                {conversionRate === '--' ? conversionRate : `${conversionRate}%`}
                            </div>
                            <div
                                className={`w-1/2 leading-10 text-center border-l border-r text-xs ${
                                    variant === winningVariant ? 'text-success' : ''
                                }`}
                            >
                                <b>
                                    {targetResults?.probability?.[variant] != undefined
                                        ? `${(targetResults.probability?.[variant] * 100).toFixed(1)}%`
                                        : '--'}
                                </b>
                            </div>
                        </div>
                    )
                },
            })
        }
    })

    return (
        <>
            <div>
                <div className="flex">
                    <div className="w-1/2">
                        <h2 className="mb-0 font-semibold text-lg">Secondary metrics</h2>
                        {metrics.length > 0 && <div className="mb-2">Monitor side effects of your experiment.</div>}
                    </div>

                    <div className="w-1/2 flex flex-col justify-end">
                        <div className="ml-auto">
                            {metrics && metrics.length > 0 && metrics.length < 3 && isExperimentRunning && (
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
                        className="secondary-metrics-table"
                        loading={secondaryMetricResultsLoading}
                        columns={columns}
                        dataSource={tabularSecondaryMetricResults}
                    />
                ) : (
                    <div className="border rounded bg-bg-light pt-6 pb-8 text-muted mt-2">
                        <div className="flex flex-col items-center mx-auto space-y-3">
                            <IconAreaChart fontSize="30" />
                            <div className="text-sm text-center text-balance">
                                Add up to 3 secondary metrics to gauge side effects of your experiment.
                            </div>
                            <LemonButton
                                icon={<IconPlus />}
                                type="secondary"
                                size="small"
                                onClick={openModalToCreateSecondaryMetric}
                            >
                                Add metric
                            </LemonButton>
                        </div>
                    </div>
                )}
            </div>
            <SecondaryMetricsModal
                onMetricsChange={onMetricsChange}
                initialMetrics={initialMetrics}
                experimentId={experimentId}
                defaultAggregationType={defaultAggregationType}
            />
        </>
    )
}

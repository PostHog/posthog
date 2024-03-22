import '../Experiment.scss'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { IconAreaChart } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'

import { InsightType } from '~/types'

import { SECONDARY_METRIC_INSIGHT_ID } from '../constants'
import { experimentLogic, TabularSecondaryMetricResults } from '../experimentLogic'
import { MetricSelector } from '../MetricSelector'
import { secondaryMetricsLogic, SecondaryMetricsProps } from '../secondaryMetricsLogic'
import { getExperimentInsightColour } from '../utils'

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
            <div>
                <div className="flex">
                    <div className="w-1/2">
                        <h2 className="mb-0 font-semibold text-lg">Secondary metrics</h2>
                        {metrics.length > 0 && (
                            <div className="mb-2">Click a metric name to compare variants on a graph.</div>
                        )}
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
        </>
    )
}

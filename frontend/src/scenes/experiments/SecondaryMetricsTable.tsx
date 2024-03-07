import './Experiment.scss'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { InsightType } from '~/types'

import { SECONDARY_METRIC_INSIGHT_ID } from './constants'
import { experimentLogic, TabularSecondaryMetricResults } from './experimentLogic'
import { getExperimentInsightColour } from './ExperimentResult'
import { MetricSelector } from './MetricSelector'
import { secondaryMetricsLogic, SecondaryMetricsProps } from './secondaryMetricsLogic'

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
                    <div
                        className="flex items-center w-fit h-5 px-1 rounded text-white text-xs"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            background: getExperimentInsightColour(getIndexForVariant(experimentResults, item.variant)),
                        }}
                    >
                        {capitalizeFirstLetter(item.variant)}
                    </div>
                )
            },
            sorter: (a, b) => String(a.variant).localeCompare(String(b.variant)),
        },
    ]

    experiment.secondary_metrics?.forEach((metric, idx) => {
        columns.push({
            key: `results_${idx}`,
            title: (
                <>
                    <div>
                        <b>{capitalizeFirstLetter(metric.name)}</b>
                    </div>
                    <div className="flex" onClick={(event) => event.stopPropagation()}>
                        <LemonButton
                            icon={<IconPencil />}
                            size="small"
                            onClick={() => openModalToEditSecondaryMetric(metric, idx)}
                        />
                    </div>
                </>
            ),
            align: 'right',
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
            sorter: (a, b) => (a.results?.[idx].result ?? 0) - (b.results?.[idx].result ?? 0),
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
                <>
                    <div className="card-secondary mt-4 mb-1">Secondary metrics</div>
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
                    {metrics && !(metrics.length > 2) && isExperimentRunning && (
                        <div className="mb-2 mt-4 justify-end">
                            <LemonButton type="secondary" size="small" onClick={openModalToCreateSecondaryMetric}>
                                Add metric
                            </LemonButton>
                        </div>
                    )}
                </>
            )}
        </>
    )
}

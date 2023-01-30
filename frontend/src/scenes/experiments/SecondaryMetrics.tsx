import { Col, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Form } from 'kea-forms'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { InsightType } from '~/types'
import './Experiment.scss'
import { secondaryMetricsLogic, SecondaryMetricsProps } from './secondaryMetricsLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { IconDelete, IconEdit } from 'lib/lemon-ui/icons'
import { LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'
import { Field } from 'lib/forms/Field'
import { MetricSelector } from './MetricSelector'
import { experimentLogic, TabularSecondaryMetricResults } from './experimentLogic'
import { getSeriesColor } from 'lib/colors'
import { capitalizeFirstLetter, humanFriendlyNumber } from 'lib/utils'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

export function SecondaryMetrics({
    onMetricsChange,
    initialMetrics,
    experimentId,
}: SecondaryMetricsProps): JSX.Element {
    const logic = secondaryMetricsLogic({ onMetricsChange, initialMetrics, experimentId })
    const {
        previewInsightId,
        metrics,
        isModalOpen,
        isSecondaryMetricModalSubmitting,
        existingModalSecondaryMetric,
        metricId,
    } = useValues(logic)

    const {
        setFilters,
        deleteMetric,
        openModalToCreateSecondaryMetric,
        openModalToEditSecondaryMetric,
        closeModal,
        saveSecondaryMetric,
        createPreviewInsight,
    } = useActions(logic)

    const {
        secondaryMetricResultsLoading,
        isExperimentRunning,
        getIndexForVariant,
        experiment,
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
                        style={{
                            color: getSeriesColor(
                                getIndexForVariant(item.variant, experiment.filters?.insight || InsightType.TRENDS)
                            ),
                        }}
                    >
                        <span className="text-sm">{capitalizeFirstLetter(item.variant)}</span>
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
                            icon={<IconEdit />}
                            size="small"
                            status="muted"
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
                                <>{(item.results[idx].result * 100).toFixed(1)}%</>
                            ) : (
                                <>{humanFriendlyNumber(item.results[idx].result)}</>
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
                width={650}
                title={existingModalSecondaryMetric ? 'Edit secondary metric' : 'New secondary metric'}
                footer={
                    <>
                        {existingModalSecondaryMetric && (
                            <LemonButton
                                className="mr-auto"
                                form="secondary-metric-modal-form"
                                type="secondary"
                                status="danger"
                                onClick={() => deleteMetric(metricId)}
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
                    props={{ onMetricsChange, initialMetrics, experimentId }}
                    formKey="secondaryMetricModal"
                    id="secondary-metric-modal-form"
                    className="space-y-4"
                >
                    <Field name="name" label="Name">
                        <LemonInput />
                    </Field>
                    <Field name="filters" label="Query">
                        {({ value, onChange }) => (
                            <MetricSelector
                                createPreviewInsight={createPreviewInsight}
                                setFilters={(payload) => {
                                    setFilters(payload)
                                    onChange(payload)
                                }}
                                previewInsightId={previewInsightId}
                                filters={value}
                            />
                        )}
                    </Field>
                </Form>
            </LemonModal>
            {experimentId == 'new' || editingExistingExperiment ? (
                <Row>
                    <Col>
                        {metrics.map((metric, idx) => (
                            <Row key={idx} className="mt-4 border rounded p-4">
                                <Row align="middle" justify="space-between" className="w-full mb-3 pb-2 border-b">
                                    <div>
                                        <b>{metric.name}</b>
                                    </div>
                                    <div className="flex">
                                        <LemonButton
                                            icon={<IconEdit />}
                                            size="small"
                                            status="muted"
                                            onClick={() => openModalToEditSecondaryMetric(metric, idx)}
                                        />
                                        <LemonButton
                                            icon={<IconDelete />}
                                            size="small"
                                            status="muted"
                                            onClick={() => deleteMetric(idx)}
                                        />
                                    </div>
                                </Row>
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
                                        showNestedArrow={true}
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
                            </Row>
                        ))}
                        {metrics && !(metrics.length > 2) && (
                            <Col>
                                <div className="mb-2 mt-4">
                                    <LemonButton type="secondary" onClick={openModalToCreateSecondaryMetric}>
                                        Add metric
                                    </LemonButton>
                                </div>
                            </Col>
                        )}
                    </Col>
                </Row>
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

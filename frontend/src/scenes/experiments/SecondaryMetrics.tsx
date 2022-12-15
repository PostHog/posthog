import { Col, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Form } from 'kea-forms'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { InsightType } from '~/types'
import './Experiment.scss'
import { secondaryMetricsLogic, SecondaryMetricsProps } from './secondaryMetricsLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { IconDelete, IconEdit } from 'lib/components/icons'
import { LemonInput, LemonModal } from '@posthog/lemon-ui'
import { Field } from 'lib/forms/Field'
import { MetricSelector } from './MetricSelector'

export function SecondaryMetrics({ onMetricsChange, initialMetrics }: SecondaryMetricsProps): JSX.Element {
    const logic = secondaryMetricsLogic({ onMetricsChange, initialMetrics })
    const { previewInsightId, metrics, isModalOpen, isSecondaryMetricModalSubmitting, existingModalSecondaryMetric } =
        useValues(logic)

    const {
        setFilters,
        deleteMetric,
        openModalToCreateSecondaryMetric,
        openModalToEditSecondaryMetric,
        closeModal,
        saveSecondaryMetric,
        createPreviewInsight,
    } = useActions(logic)

    return (
        <>
            <LemonModal
                isOpen={isModalOpen}
                onClose={closeModal}
                width={650}
                title={existingModalSecondaryMetric ? 'Edit secondary metric' : 'New secondary metric'}
                footer={
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
                }
            >
                <Form
                    logic={secondaryMetricsLogic}
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
        </>
    )
}

import { Button, Col, Input, Modal, Row, Form, Select } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId, InsightType } from '~/types'
import './Experiment.scss'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { CaretDownOutlined, DeleteOutlined } from '@ant-design/icons'
import { secondaryMetricsLogic, SecondaryMetricsProps } from './secondaryMetricsLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

export function SecondaryMetrics({ onMetricsChange, initialMetrics }: SecondaryMetricsProps): JSX.Element {
    const logic = secondaryMetricsLogic({ onMetricsChange, initialMetrics })
    const { previewInsightId, metrics, modalVisible, currentMetric } = useValues(logic)

    const {
        createNewMetric,
        updateMetricFilters,
        setFilters,
        showModal,
        hideModal,
        changeInsightType,
        setCurrentMetricName,
        deleteMetric,
    } = useActions(logic)

    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: previewInsightId as InsightShortId,
            syncWithUrl: false,
        })
    )

    const { isStepsEmpty, filterSteps } = useValues(funnelLogic(insightProps))
    return (
        <>
            <Modal
                title="Add secondary metric"
                visible={modalVisible}
                destroyOnClose={true}
                onCancel={hideModal}
                footer={null}
                style={{ minWidth: 600 }}
            >
                <Form
                    layout="vertical"
                    initialValues={{ type: InsightType.TRENDS }}
                    onValuesChange={(values) => {
                        if (values.name) {
                            setCurrentMetricName(values.name)
                        }
                    }}
                    onFinish={() => {
                        createNewMetric()
                        hideModal()
                    }}
                    scrollToFirstError
                    requiredMark={false}
                >
                    <Form.Item
                        name="name"
                        label="Name"
                        rules={[{ required: true, message: 'You have to enter a name.' }]}
                    >
                        <Input />
                    </Form.Item>
                    <Form.Item name="type" label="Type">
                        <Select
                            style={{ display: 'flex' }}
                            value={currentMetric.filters.insight}
                            onChange={() => {
                                changeInsightType()
                            }}
                            suffixIcon={<CaretDownOutlined />}
                            dropdownMatchSelectWidth={false}
                        >
                            <Select.Option value={InsightType.TRENDS}>
                                <Col>
                                    <span>
                                        <b>Trend</b>
                                    </span>
                                </Col>
                            </Select.Option>
                            <Select.Option value={InsightType.FUNNELS}>
                                <Col>
                                    <span>
                                        <b>Conversion funnel</b>
                                    </span>
                                </Col>
                            </Select.Option>
                        </Select>
                    </Form.Item>
                    <Form.Item name="query" label="Query">
                        {currentMetric.filters.insight === InsightType.FUNNELS && (
                            <ActionFilter
                                bordered
                                filters={currentMetric.filters}
                                setFilters={(payload) => {
                                    const newFilters = {
                                        ...currentMetric.filters,
                                        insight: InsightType.FUNNELS,
                                        ...payload,
                                    }
                                    updateMetricFilters(newFilters)
                                    setFilters(newFilters)
                                }}
                                typeKey={'funnel-preview-metric'}
                                mathAvailability={MathAvailability.None}
                                hideDeleteBtn={filterSteps.length === 1}
                                buttonCopy="Add funnel step"
                                showSeriesIndicator={!isStepsEmpty}
                                seriesIndicatorType="numeric"
                                sortable
                                showNestedArrow={true}
                                propertiesTaxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.EventProperties,
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.Cohorts,
                                    TaxonomicFilterGroupType.Elements,
                                ]}
                            />
                        )}
                        {currentMetric.filters.insight === InsightType.TRENDS && (
                            <ActionFilter
                                bordered
                                entitiesLimit={1}
                                filters={currentMetric.filters}
                                setFilters={(payload) => {
                                    const newFilters = {
                                        ...currentMetric.filters,
                                        insight: InsightType.TRENDS,
                                        ...payload,
                                    }
                                    updateMetricFilters(newFilters)
                                    setFilters(newFilters)
                                }}
                                typeKey={'trend-preview-metric'}
                                buttonCopy="Add graph series"
                                showSeriesIndicator
                                propertiesTaxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.EventProperties,
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.Cohorts,
                                    TaxonomicFilterGroupType.Elements,
                                ]}
                            />
                        )}
                    </Form.Item>
                    <Form.Item name="metric-preview" label="Metric preview">
                        <BindLogic logic={insightLogic} props={insightProps}>
                            <InsightContainer disableHeader={true} disableTable={true} disableCorrelationTable={true} />
                        </BindLogic>
                    </Form.Item>
                    <Row justify="end">
                        <LemonButton type="secondary" className="mr-2" onClick={() => hideModal()}>
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" htmlType="submit">
                            Save
                        </LemonButton>
                    </Row>
                </Form>
            </Modal>
            <Row>
                <Col>
                    {metrics.map((metric, idx) => (
                        <Row key={idx} className="mt-4">
                            <Row align="middle" className="w-full rounded border-all" style={{ padding: 8 }}>
                                <div style={{ fontWeight: 500 }}>Name</div>{' '}
                                <div className="metric-name">{metric.name}</div>
                                <DeleteOutlined
                                    className="text-danger"
                                    style={{ padding: 8 }}
                                    onClick={() => deleteMetric(idx)}
                                />
                            </Row>
                            {metric.filters.insight === InsightType.FUNNELS && (
                                <ActionFilter
                                    bordered
                                    filters={metric.filters}
                                    setFilters={(payload) => {
                                        const newFilters = {
                                            ...metric.filters,
                                            insight: InsightType.FUNNELS,
                                            ...payload,
                                        }
                                        updateMetricFilters(newFilters)
                                        setFilters(newFilters)
                                    }}
                                    typeKey={`funnel-preview-${idx}`}
                                    mathAvailability={MathAvailability.None}
                                    hideDeleteBtn={filterSteps.length === 1}
                                    buttonCopy="Add funnel step"
                                    showSeriesIndicator={!isStepsEmpty}
                                    seriesIndicatorType="numeric"
                                    sortable
                                    showNestedArrow={true}
                                    propertiesTaxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.EventProperties,
                                        TaxonomicFilterGroupType.PersonProperties,
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
                                    setFilters={(payload) => {
                                        const newFilters = {
                                            ...metric.filters,
                                            insight: InsightType.TRENDS,
                                            ...payload,
                                        }
                                        updateMetricFilters(newFilters)
                                        setFilters(newFilters)
                                    }}
                                    typeKey={`trend-preview-${idx}`}
                                    buttonCopy="Add graph series"
                                    showSeriesIndicator
                                    entitiesLimit={1}
                                    propertiesTaxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.EventProperties,
                                        TaxonomicFilterGroupType.PersonProperties,
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
                                <Button style={{ color: 'var(--primary)', minWidth: 240 }} onClick={showModal}>
                                    Add metric
                                </Button>
                            </div>
                        </Col>
                    )}
                </Col>
            </Row>
        </>
    )
}

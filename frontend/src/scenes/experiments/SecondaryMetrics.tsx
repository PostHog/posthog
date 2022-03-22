import { Button, Card, Col, Input, Modal, Row, Form, Select } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId, InsightType } from '~/types'
import './Experiment.scss'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { CaretDownOutlined, DeleteOutlined } from '@ant-design/icons'
import { secondaryMetricsLogic, SecondaryMetricsProps } from './secondaryMetricsLogic'

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
                onOk={() => {
                    createNewMetric()
                    hideModal()
                }}
                okText="Save"
                style={{ minWidth: 600 }}
            >
                <Form
                    layout="vertical"
                    initialValues={{ name: '', type: InsightType.TRENDS }}
                    onValuesChange={(values) => {
                        if (values.name) {
                            setCurrentMetricName(values.name)
                        }
                    }}
                >
                    <Form.Item name="name" label="Name">
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
                        <Card
                            className="action-filters-bordered"
                            style={{ width: '100%', marginRight: 8 }}
                            bodyStyle={{ padding: 0 }}
                        >
                            {currentMetric.filters.insight === InsightType.FUNNELS && (
                                <ActionFilter
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
                                    hideMathSelector={true}
                                    hideDeleteBtn={filterSteps.length === 1}
                                    buttonCopy="Add funnel step"
                                    showSeriesIndicator={!isStepsEmpty}
                                    seriesIndicatorType="numeric"
                                    fullWidth
                                    sortable
                                    showNestedArrow={true}
                                    propertiesTaxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.EventProperties,
                                        TaxonomicFilterGroupType.PersonProperties,
                                        TaxonomicFilterGroupType.Cohorts,
                                        TaxonomicFilterGroupType.Elements,
                                    ]}
                                    rowClassName="action-filters-bordered"
                                />
                            )}
                            {currentMetric.filters.insight === InsightType.TRENDS && (
                                <ActionFilter
                                    entitiesLimit={1}
                                    horizontalUI
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
                                    hideMathSelector={false}
                                    propertiesTaxonomicGroupTypes={[
                                        TaxonomicFilterGroupType.EventProperties,
                                        TaxonomicFilterGroupType.PersonProperties,
                                        TaxonomicFilterGroupType.Cohorts,
                                        TaxonomicFilterGroupType.Elements,
                                    ]}
                                />
                            )}
                        </Card>
                    </Form.Item>
                    <Form.Item name="metric-preview" label="Metric preview">
                        <BindLogic logic={insightLogic} props={insightProps}>
                            <InsightContainer disableHeader={true} disableTable={true} />
                        </BindLogic>
                    </Form.Item>
                </Form>
            </Modal>
            <Row>
                <Col>
                    {metrics.map((metric, idx) => (
                        <Row key={idx} className="mt">
                            <Row align="middle" className="full-width border-all" style={{ padding: 8 }}>
                                <div style={{ fontWeight: 500 }}>Name</div>{' '}
                                <div className="metric-name">
                                    {metric.name ? metric.name : `${metric.filters.insight} metric`}
                                </div>
                                <DeleteOutlined
                                    className="text-danger"
                                    style={{ padding: 8 }}
                                    onClick={() => deleteMetric(idx)}
                                />
                            </Row>
                            <Card className="full-width" style={{ borderTop: 'none' }} bodyStyle={{ padding: 0 }}>
                                {metric.filters.insight === InsightType.FUNNELS && (
                                    <ActionFilter
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
                                        hideMathSelector={true}
                                        hideDeleteBtn={filterSteps.length === 1}
                                        buttonCopy="Add funnel step"
                                        showSeriesIndicator={!isStepsEmpty}
                                        seriesIndicatorType="numeric"
                                        fullWidth
                                        sortable
                                        showNestedArrow={true}
                                        propertiesTaxonomicGroupTypes={[
                                            TaxonomicFilterGroupType.EventProperties,
                                            TaxonomicFilterGroupType.PersonProperties,
                                            TaxonomicFilterGroupType.Cohorts,
                                            TaxonomicFilterGroupType.Elements,
                                        ]}
                                        rowClassName="action-filters-bordered"
                                        readOnly={true}
                                    />
                                )}
                                {metric.filters.insight === InsightType.TRENDS && (
                                    <ActionFilter
                                        horizontalUI
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
                                        hideMathSelector={false}
                                        propertiesTaxonomicGroupTypes={[
                                            TaxonomicFilterGroupType.EventProperties,
                                            TaxonomicFilterGroupType.PersonProperties,
                                            TaxonomicFilterGroupType.Cohorts,
                                            TaxonomicFilterGroupType.Elements,
                                        ]}
                                        readOnly={true}
                                    />
                                )}
                            </Card>
                        </Row>
                    ))}
                    {metrics && !(metrics.length > 2) && (
                        <Col>
                            <div className="mb-05 mt">
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

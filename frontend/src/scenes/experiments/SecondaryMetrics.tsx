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
import { CaretDownOutlined } from '@ant-design/icons'
import { secondaryMetricsLogic, SecondaryMetricsProps } from './secondaryMetricsLogic'

export function SecondaryMetrics({ onMetricsChange, initialMetrics }: SecondaryMetricsProps): JSX.Element {
    const logic = secondaryMetricsLogic({ onMetricsChange, initialMetrics })
    const { previewInsightId, metrics, modalVisible, metric } = useValues(logic)

    const { createNewMetric, updateMetricFilters, setFilters, showModal, hideModal } = useActions(logic)

    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: previewInsightId as InsightShortId,
            syncWithUrl: false,
        })
    )

    console.log(insightProps)
    console.log('previewID: ', previewInsightId)
    console.log(metrics)

    const { isStepsEmpty, filterSteps } = useValues(funnelLogic(insightProps))

    return (
        <>
            <Modal title="Add secondary metric" visible={modalVisible} onCancel={hideModal} onOk={hideModal} okText="Save" width={600}>
                <Form layout="vertical"
                    onFinish={() => {
                        hideModal()
                    }}
                >
                    <Form.Item name="name" label="Name">
                        <Input />
                    </Form.Item>
                    <Form.Item name="type" label="Type">
                        <Select
                            style={{ display: 'flex' }}
                            value={InsightType.TRENDS}
                            defaultValue={InsightType.TRENDS}
                            onChange={() => { }}
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
                            {metric.filters.insight === InsightType.FUNNELS && (
                                <ActionFilter
                                    filters={metric.filters}
                                    setFilters={(payload) => {
                                        const newFilters = {
                                            ...metric.filters,
                                            insight: InsightType.FUNNELS,
                                            ...payload,
                                        }
                                        // updateMetricFilters(metricId, newFilters)
                                        setFilters(newFilters)
                                    }}
                                    // typeKey={`funnel-preview-${metricId}`}
                                    typeKey={`funnel-preview-${1}`}

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
                                        // updateMetricFilters(metricId, newFilters)
                                        setFilters(newFilters)
                                    }}
                                    // typeKey={`trend-preview-${metricId}`}
                                    typeKey={`funnel-preview-${1}`}

                                    buttonCopy="Add graph series"
                                    showSeriesIndicator
                                    // singleFilter={true}
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
                        {/* <Col span={14}> */}
                        <BindLogic logic={insightLogic} props={insightProps}>
                            <InsightContainer disableHeader={true} disableTable={true} />
                        </BindLogic>
                        {/* </Col> */}
                    </Form.Item>
                </Form>
            </Modal>
            <Row style={{ width: '100%' }}>
                <Col span={10} style={{ paddingRight: 8 }}>
                    {metrics.map((metric, metricId) => (
                        <Row key={metricId}>
                            <Card
                                className="action-filters-bordered"
                                style={{ width: '100%', marginRight: 8 }}
                                bodyStyle={{ padding: 0 }}
                            >
                                {metric.filters.insight === InsightType.FUNNELS && (
                                    <ActionFilter
                                        filters={metric.filters}
                                        setFilters={(payload) => {
                                            const newFilters = {
                                                ...metric.filters,
                                                insight: InsightType.FUNNELS,
                                                ...payload,
                                            }
                                            updateMetricFilters(metricId, newFilters)
                                            setFilters(newFilters)
                                        }}
                                        typeKey={`funnel-preview-${metricId}`}
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
                                            updateMetricFilters(metricId, newFilters)
                                            setFilters(newFilters)
                                        }}
                                        typeKey={`trend-preview-${metricId}`}
                                        buttonCopy="Add graph series"
                                        showSeriesIndicator
                                        // singleFilter={true}
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
                        </Row>
                    ))}
                    <Col>
                        <div className="mb-05 mt">
                            <Button
                                style={{ color: 'var(--primary)', minWidth: 240 }}
                                onClick={showModal}

                            >
                                Add metric
                            </Button>
                            {/* <Button
                                style={{ color: 'var(--primary)', minWidth: 240 }}
                                icon={<PlusOutlined />}
                                // onClick={showModal}
                                // onClick={() => createNewMetric(InsightType.TRENDS)}
                            >
                                Add trend metric
                            </Button> */}
                        </div>
                        {/* <div>
                            <Button
                                style={{ color: 'var(--primary)', minWidth: 240 }}
                                icon={<PlusOutlined />}
                                onClick={() => createNewMetric(InsightType.FUNNELS)}
                            >
                                Add conversion metric
                            </Button>
                        </div> */}
                    </Col>
                </Col>
            </Row>
        </>
    )
}

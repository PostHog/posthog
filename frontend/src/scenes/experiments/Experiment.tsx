import SaveOutlined from '@ant-design/icons/lib/icons/SaveOutlined'
import { Button, Card, Col, Form, Input, Row } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React, { useState } from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'
import { PropertyFilter } from '~/types'
import './Experiment.scss'
import { experimentLogic } from './experimentLogic'
import { InsightContainer } from 'scenes/insights/InsightContainer'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentLogic,
}

export function Experiment(): JSX.Element {
    const { user } = useValues(userLogic)
    const { newExperimentData, experimentId, experimentData, experimentFunnel } = useValues(experimentLogic)
    const { setNewExperimentData, createExperiment, setFilters } = useActions(experimentLogic)
    const [form] = Form.useForm()
    const [page, setPage] = useState(1)
    const nextPage = (): void => setPage(page + 1)
    const prevPage = (): void => setPage(page - 1)

    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: experimentFunnel?.short_id,
            filters: experimentFunnel?.filters,
            syncWithUrl: false,
        })
    )
    const { isStepsEmpty, filterSteps, filters } = useValues(funnelLogic(insightProps))

    return (
        <>
            {experimentId === 'new' ? (<BindLogic
                logic={insightLogic}
                props={{
                    dashboardItemId: experimentFunnel?.short_id,
                    filters: experimentFunnel?.filters,
                    syncWithUrl: false,
                }}
            >
                <Row
                    align="middle"
                    justify="space-between"
                    style={{ borderBottom: '1px solid var(--border)', marginBottom: '1rem', paddingBottom: 8 }}
                >
                    <PageHeader title={newExperimentData?.name || 'New Experiment'} />
                    <Button
                        style={{ color: 'var(--primary)', borderColor: 'var(--primary)' }}
                        onClick={() => createExperiment(true)}
                    >
                        Save as draft
                    </Button>
                </Row>
                <Form
                    name="new-experiment"
                    layout="vertical"
                    className="experiment-form"
                    form={form}
                    onFinish={(values) => setNewExperimentData(values)}
                >
                    {page === 0 && (
                        <div>
                            <Form.Item label="Name" name="name">
                                <Input data-attr="experiment-name" className="ph-ignore-input" />
                            </Form.Item>
                            <Form.Item label="Feature flag key" name="feature_flag_key">
                                <Input data-attr="experiment-feature-flag-key" />
                            </Form.Item>
                            <Form.Item label="Description" name="description">
                                <Input.TextArea
                                    data-attr="experiment-description"
                                    className="ph-ignore-input"
                                    placeholder="Adding a helpful description can ensure others know what this experiment is about."
                                />
                            </Form.Item>
                            <Form.Item className="text-right">
                                <Button icon={<SaveOutlined />} htmlType="submit" type="primary" onClick={nextPage}>
                                    Save and continue
                                </Button>
                            </Form.Item>
                        </div>
                    )}

                    {page === 1 && (
                        <div>
                            <Form.Item className="person-selection" label="Person selection">
                                <Form.Item name="person-selection">
                                    <span className="text-muted">
                                        Select the persons who will participate in this experiment. We'll split all persons
                                        evenly in a control and experiment group.
                                    </span>
                                    <div style={{ flex: 3, marginRight: 5 }}>
                                        <PropertyFilters
                                            endpoint="person"
                                            pageKey={'EditFunnel-property'}
                                            propertyFilters={filters.properties || []}
                                            onChange={(anyProperties) => {
                                                form.setFieldsValue({ filters: { properties: anyProperties } })
                                                setFilters({
                                                    properties: anyProperties.filter(isValidPropertyFilter),
                                                })
                                            }}
                                            style={{ margin: '1rem 0 0' }}
                                            taxonomicGroupTypes={[
                                                TaxonomicFilterGroupType.PersonProperties,
                                                TaxonomicFilterGroupType.CohortsWithAllUsers,
                                            ]}
                                            popoverPlacement="top"
                                            taxonomicPopoverPlacement="auto"
                                        />
                                    </div>
                                </Form.Item>
                            </Form.Item>
                            <Form.Item className="metrics-selection" label="Goal metric">
                                <Form.Item name="metrics-selection">
                                    <BindLogic
                                        logic={insightLogic}
                                        props={{
                                            dashboardItemId: experimentFunnel?.short_id,
                                            filters: experimentFunnel?.filters,
                                            syncWithUrl: false,
                                        }}
                                    >
                                        <Row>
                                            <Col span={8}>
                                                <Row className="text-muted" style={{ marginBottom: '1rem' }}>
                                                    Define the metric which you are trying to optimize. This is the most
                                                    important part of your experiment.
                                                </Row>
                                                <Row>
                                                    <Card
                                                        className="action-filters-bordered"
                                                        style={{ width: '100%', marginRight: 8 }}
                                                        bodyStyle={{ padding: 0 }}
                                                    >
                                                        <ActionFilter
                                                            filters={filters}
                                                            setFilters={setFilters}
                                                            typeKey={`EditFunnel-action`}
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
                                                    </Card>
                                                </Row>
                                            </Col>
                                            <Col span={16}>
                                                <InsightContainer />
                                            </Col>
                                        </Row>
                                    </BindLogic>
                                </Form.Item>
                            </Form.Item>
                            <Row justify="space-between">
                                <Button onClick={prevPage}>Go back</Button>
                                <Button icon={<SaveOutlined />} htmlType="submit" type="primary" onClick={nextPage}>
                                    Save and preview
                                </Button>
                            </Row>
                        </div>
                    )}

                    {page === 2 && (
                        <div className="confirmation">
                            <PageHeader title={newExperimentData?.name || ''} />
                            <div>{newExperimentData?.description}</div>
                            <div>Owner: {user?.first_name}</div>
                            <div>Feature flag key: {newExperimentData?.feature_flag}</div>
                            <Row>
                                <Col>
                                    <Row>Person allocation</Row>
                                    <Row>The following users will participate in the experiment</Row>
                                    <ul>
                                        {newExperimentData?.filters?.properties?.map((property: PropertyFilter, idx: number) => (
                                            <li key={idx}>
                                                Users with {property.key} {property.operator}{' '}
                                                {Array.isArray(property.value)
                                                    ? property.value.map((val) => `${val}, `)
                                                    : property.value}
                                            </li>
                                        ))}
                                    </ul>
                                </Col>
                            </Row>
                            <Row justify="space-between">
                                <Button onClick={prevPage}>Go back</Button>
                                <Button type="primary" onClick={() => createExperiment()}>
                                    Save and launch
                                </Button>
                            </Row>
                        </div>
                    )}
                </Form>
            </BindLogic>) : experimentData ? (
                <>
                    <div>
                        <PageHeader title={experimentData.name} />
                        <div>{experimentData?.description}</div>
                        <div>Owner: {experimentData.created_by?.first_name}</div>
                        <div>Feature flag key: {experimentData?.feature_flag_key}</div>
                    </div>
                </>
            ) : (
                <div>Loading...</div>
            )}
        </>
    )
}

import SaveOutlined from '@ant-design/icons/lib/icons/SaveOutlined'
import { Button, Card, Col, Form, Input, Row } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { FunnelVizType, PropertyFilter } from '~/types'
import './Experiment.scss'
import { experimentLogic } from './experimentLogic'
import { InsightContainer } from 'scenes/insights/InsightContainer'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentLogic,
}

export function Experiment(): JSX.Element {
    const {
        newExperimentData,
        experimentId,
        experimentData,
        experimentFunnel,
        newExperimentCurrentPage,
        experimentResults,
    } = useValues(experimentLogic)
    const { setNewExperimentData, createExperiment, setFilters, nextPage, prevPage } = useActions(experimentLogic)
    const [form] = Form.useForm()

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
            {experimentId === 'new' || !experimentData?.start_date ? (
                <>
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
                        onValuesChange={(values) => setNewExperimentData(values)}
                        initialValues={{
                            name: newExperimentData?.name,
                            feature_flag_key: newExperimentData?.feature_flag_key,
                            description: newExperimentData?.description,
                        }}
                        onFinish={(values) => {
                            setNewExperimentData(values)
                            nextPage()
                        }}
                    >
                        {newExperimentCurrentPage === 0 && (
                            <div>
                                <Form.Item
                                    label="Name"
                                    name="name"
                                    rules={[{ required: true, message: 'You have to enter a name.' }]}
                                >
                                    <Input data-attr="experiment-name" className="ph-ignore-input" />
                                </Form.Item>
                                <Form.Item
                                    label="Feature flag key"
                                    name="feature_flag_key"
                                    rules={[{ required: true, message: 'You have to enter a feature flag key.' }]}
                                >
                                    <Input data-attr="experiment-feature-flag-key" />
                                </Form.Item>
                                <Form.Item label="Description" name="description">
                                    <Input.TextArea
                                        data-attr="experiment-description"
                                        className="ph-ignore-input"
                                        placeholder="Adding a helpful description can ensure others know what this experiment is about."
                                    />
                                </Form.Item>
                                <Button icon={<SaveOutlined />} type="primary" htmlType="submit">
                                    Save and continue
                                </Button>
                            </div>
                        )}

                        {newExperimentCurrentPage === 1 && (
                            <div>
                                <Col className="person-selection">
                                    <div className="l3 mb">Person selection</div>
                                    <div className="text-muted">
                                        Select the persons who will participate in this experiment. We'll split all
                                        persons evenly in a control and experiment group.
                                    </div>
                                    <div style={{ flex: 3, marginRight: 5 }}>
                                        <PropertyFilters
                                            endpoint="person"
                                            pageKey={'EditFunnel-property'}
                                            propertyFilters={filters.properties || []}
                                            onChange={(anyProperties) => {
                                                setNewExperimentData({
                                                    filters: { properties: anyProperties as PropertyFilter[] },
                                                })
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
                                </Col>
                                <Row className="metrics-selection">
                                    <BindLogic logic={insightLogic} props={insightProps}>
                                        <Row style={{ width: '100%' }}>
                                            <Col span={8} style={{ paddingRight: 8 }}>
                                                <div className="l3 mb">Goal metric</div>
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
                                                            setFilters={(actionFilters) => {
                                                                setNewExperimentData({ filters: actionFilters })
                                                                setFilters(actionFilters)
                                                            }}
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
                                                <InsightContainer disableTable={true} />
                                            </Col>
                                        </Row>
                                    </BindLogic>
                                </Row>
                                <Row justify="space-between">
                                    <Button onClick={prevPage}>Go back</Button>
                                    <Button icon={<SaveOutlined />} type="primary" onClick={nextPage}>
                                        Save and preview
                                    </Button>
                                </Row>
                            </div>
                        )}

                        {newExperimentCurrentPage === 2 && (
                            <div className="confirmation">
                                <div>Name: {newExperimentData?.name}</div>
                                {newExperimentData?.description && (
                                    <div>Description: {newExperimentData?.description}</div>
                                )}
                                <div>Feature flag key: {newExperimentData?.feature_flag_key}</div>
                                <Row>
                                    <Col>
                                        <Row>Person allocation:</Row>
                                        <Row>The following users will participate in the experiment</Row>
                                        <ul>
                                            {newExperimentData?.filters?.properties?.length ? (
                                                newExperimentData.filters.properties.map(
                                                    (property: PropertyFilter, idx: number) => (
                                                        <li key={idx}>
                                                            Users with {property.key} {property.operator}{' '}
                                                            {Array.isArray(property.value)
                                                                ? property.value.map((val) => `${val}, `)
                                                                : property.value}
                                                        </li>
                                                    )
                                                )
                                            ) : (
                                                <li key={'all users'}>All users</li>
                                            )}
                                        </ul>
                                    </Col>
                                </Row>
                                <Row>
                                    <Col>
                                        <Row>Experiment parameters:</Row>
                                        <Row>
                                            <ul>
                                                <li>Target confidence level: </li>
                                                <li>Approx. run time: </li>
                                                <li>Approx. sample size: </li>
                                            </ul>
                                        </Row>
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
                </>
            ) : experimentData ? (
                <div className="experiment-result">
                    <div>
                        <PageHeader title={experimentData.name} />
                        <div>{experimentData?.description}</div>
                        <div>Owner: {experimentData.created_by?.first_name}</div>
                        <div>Feature flag key: {experimentData?.feature_flag_key}</div>
                    </div>

                    {experimentResults && (
                        <BindLogic
                            logic={insightLogic}
                            props={{
                                dashboardItemId: experimentResults.itemID,
                                filters: {
                                    ...experimentResults.filters,
                                    insight: 'FUNNELS',
                                    funnel_viz_type: FunnelVizType.Steps,
                                    display: 'FunnelViz',
                                },
                                cachedResults: experimentResults.funnel,
                                syncWithUrl: false,
                                doNotLoad: true,
                            }}
                        >
                            <div>
                                <PageHeader title="Results" />
                                <div>Probability: {experimentResults.probability}</div>
                                <InsightContainer disableTable={true} />
                            </div>
                        </BindLogic>
                    )}
                </div>
            ) : (
                <div>Loading...</div>
            )}
        </>
    )
}

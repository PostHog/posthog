import SaveOutlined from '@ant-design/icons/lib/icons/SaveOutlined'
import { Button, Card, Col, Form, Input, Row, Slider, Tooltip } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters'
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
import { InfoCircleOutlined } from '@ant-design/icons'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentLogic,
}

export function Experiment(): JSX.Element {
    const {
        newExperimentData,
        experimentId,
        experimentData,
        experimentFunnelId,
        minimimumDetectableChange,
        recommendedSampleSize,
        expectedRunningTime,
        newExperimentCurrentPage,
        experimentResults,
    } = useValues(experimentLogic)
    const { setNewExperimentData, createExperiment, setFilters, nextPage, prevPage } = useActions(experimentLogic)

    const [form] = Form.useForm()

    const { insightProps } = useValues(
        insightLogic({
            dashboardItemId: experimentFunnelId,
            syncWithUrl: false,
        })
    )
    const { isStepsEmpty, filterSteps, filters, results, conversionMetrics } = useValues(funnelLogic(insightProps))

    const conversionRate = conversionMetrics.totalRate * 100
    const entrants = results?.[0]?.count

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
                                <Row className="person-selection">
                                    <Col>
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
                                </Row>
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
                                <Row className="mde-selection">
                                    <Row style={{ width: '100%', marginBottom: 8 }} align="middle" justify="center">
                                        <Row
                                            style={{ width: '100%', fontWeight: 500, fontSize: 16 }}
                                            className="text-muted"
                                            justify="center"
                                        >
                                            Estimates for how long your experiment should run.
                                        </Row>
                                        <Col span={8}>
                                            <Slider
                                                defaultValue={5}
                                                min={1}
                                                max={50}
                                                trackStyle={{ background: 'black' }}
                                                onChange={(value) => {
                                                    setNewExperimentData({
                                                        parameters: { minimum_detectable_effect: value },
                                                    })
                                                }}
                                                tipFormatter={(value) => `${value}%`}
                                                marks={
                                                    Math.floor(conversionRate) > 0
                                                        ? {
                                                              [Math.floor(conversionRate)]: `${Math.floor(
                                                                  conversionRate
                                                              )}%`,
                                                              5: `5%`,
                                                              10: `10%`,
                                                          }
                                                        : { 5: `5%`, 10: `10%` }
                                                }
                                            />
                                        </Col>
                                    </Row>
                                    <Row style={{ width: '100%' }} justify="center" className="estimates">
                                        <div style={{ paddingRight: 16, fontWeight: 600, fontSize: 18 }}>
                                            <div className="text-center">{conversionRate.toFixed(1)}%</div>
                                            <div className="estimate">Baseline conversion rate</div>
                                        </div>
                                        <div
                                            style={{
                                                paddingLeft: 16,
                                                paddingRight: 16,
                                                borderLeft: '1px solid var(--border)',
                                                borderRight: '1px solid var(--border)',
                                                fontWeight: 600,
                                                fontSize: 18,
                                            }}
                                        >
                                            <div className="text-center">
                                                {Math.max(0, conversionRate - minimimumDetectableChange).toFixed()}% -{' '}
                                                {Math.min(100, conversionRate + minimimumDetectableChange).toFixed()}%
                                            </div>
                                            <div className="estimate text-center">
                                                Threshold of caring
                                                <Tooltip
                                                    title={`The minimum % change in conversion rate you care about. 
                                                    This means you don't care about variants whose
                                                    conversion rate is between these two percentages.`}
                                                >
                                                    <InfoCircleOutlined style={{ marginLeft: 4 }} />
                                                </Tooltip>
                                            </div>
                                        </div>
                                        <div
                                            style={{
                                                paddingLeft: 16,
                                                paddingRight: 16,
                                                borderLeft: '1px solid var(--border)',
                                                borderRight: '1px solid var(--border)',
                                                fontWeight: 600,
                                                fontSize: 18,
                                            }}
                                        >
                                            <div className="text-center">~{recommendedSampleSize(conversionRate)}</div>
                                            <div className="estimate">Recommended # of people</div>
                                        </div>
                                        <div style={{ paddingLeft: 16, fontWeight: 600, fontSize: 18 }}>
                                            <div className="text-center">
                                                ~{expectedRunningTime(entrants, recommendedSampleSize(conversionRate))}
                                            </div>
                                            <div className="estimate">Recommended days</div>
                                        </div>
                                    </Row>
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

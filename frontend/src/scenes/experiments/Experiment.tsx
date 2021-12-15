import SaveOutlined from '@ant-design/icons/lib/icons/SaveOutlined'
import { Alert, Button, Card, Col, Collapse, Form, Input, InputNumber, Row, Tooltip } from 'antd'
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
import { JSSnippet } from 'scenes/feature-flags/FeatureFlagSnippets'
import { IconJavascript } from 'lib/components/icons'
import { InfoCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { LemonButton } from 'lib/components/LemonButton'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

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
        minimumDetectableChange,
        recommendedSampleSize,
        expectedRunningTime,
        newExperimentCurrentPage,
        experimentResults,
    } = useValues(experimentLogic)
    const { setNewExperimentData, createExperiment, setFilters, nextPage, prevPage, endExperiment } =
        useActions(experimentLogic)

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
                        <PageHeader title={'New Experiment'} />
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
                        scrollToFirstError
                    >
                        {newExperimentCurrentPage === 0 && (
                            <div>
                                <Row>
                                    <Col span={12} style={{ paddingRight: 24 }}>
                                        <Form.Item
                                            label="Name"
                                            name="name"
                                            rules={[{ required: true, message: 'You have to enter a name.' }]}
                                        >
                                            <Input data-attr="experiment-name" className="ph-ignore-input" />
                                        </Form.Item>
                                        <span className="text-small text-muted">
                                            We are creating a new feature flag here that is unique to the experiment
                                        </span>
                                        <Form.Item
                                            label="Feature flag key"
                                            name="feature_flag_key"
                                            rules={[
                                                {
                                                    required: true,
                                                    message: 'You have to create a new feature flag key.',
                                                },
                                            ]}
                                        >
                                            <Input
                                                data-attr="experiment-feature-flag-key"
                                                placeholder="examples: new-landing-page-experiment, betaFeatureExperiment, ab_test_1_experiment"
                                            />
                                        </Form.Item>
                                        <Form.Item label="Description" name="description">
                                            <Input.TextArea
                                                data-attr="experiment-description"
                                                className="ph-ignore-input"
                                                placeholder="Adding a helpful description can ensure others know what this experiment is about."
                                            />
                                        </Form.Item>
                                    </Col>
                                    <Col span={12}>
                                        <Card className="experiment-preview">
                                            <Row className="preview-row">
                                                <Col>
                                                    <div className="card-secondary">Preview</div>
                                                    <div>
                                                        <span className="mr-05">
                                                            <b>{newExperimentData?.name}</b>
                                                        </span>
                                                        {newExperimentData?.feature_flag_key && (
                                                            <CopyToClipboardInline
                                                                explicitValue={newExperimentData.feature_flag_key}
                                                                iconStyle={{ color: 'var(--text-muted-alt)' }}
                                                                description="feature flag key"
                                                            >
                                                                <span className="text-muted">
                                                                    {newExperimentData?.feature_flag_key}
                                                                </span>
                                                            </CopyToClipboardInline>
                                                        )}
                                                    </div>
                                                </Col>
                                            </Row>
                                            <Row className="preview-row">
                                                <Col span={12}>
                                                    <div className="card-secondary">Target Participant Count</div>
                                                    <div className="pb">
                                                        <span className="l4">
                                                            ~{recommendedSampleSize(conversionRate)}
                                                        </span>{' '}
                                                        persons
                                                    </div>
                                                    <div className="card-secondary">Baseline Conversion Rate</div>
                                                    <div className="l4">{conversionRate.toFixed(1)}%</div>
                                                </Col>
                                                <Col span={12}>
                                                    <div className="card-secondary">Target duration</div>
                                                    <div>
                                                        <span className="l4">
                                                            ~
                                                            {expectedRunningTime(
                                                                entrants,
                                                                recommendedSampleSize(conversionRate)
                                                            )}
                                                        </span>{' '}
                                                        days
                                                    </div>
                                                </Col>
                                            </Row>
                                            <Row className="preview-row">
                                                <Col>
                                                    <div className="l4">
                                                        Conversion goal threshold
                                                        <Tooltip
                                                            title={`The minimum % change in conversion rate you care about. 
                                                    This means you don't care about variants whose
                                                    conversion rate is between these two percentages.`}
                                                        >
                                                            <InfoCircleOutlined style={{ marginLeft: 4 }} />
                                                        </Tooltip>
                                                    </div>
                                                    <div className="pb text-small text-muted">
                                                        Apply a threshold to broaden the acceptable range of conversion
                                                        rates for this experiment. The acceptable range will be the
                                                        baseline conversion goal +/- the goal threshold.
                                                    </div>
                                                    <div>
                                                        <span className="l4 pr">Threshold value</span>
                                                        <InputNumber
                                                            min={1}
                                                            max={50}
                                                            defaultValue={5}
                                                            formatter={(value) => `${value}%`}
                                                            onChange={(value) =>
                                                                setNewExperimentData({
                                                                    parameters: { minimum_detectable_effect: value },
                                                                })
                                                            }
                                                        />
                                                    </div>
                                                </Col>
                                            </Row>
                                            <Row className="preview-row">
                                                <Col>
                                                    <div className="card-secondary mb-05">Conversion goal range</div>
                                                    <div>
                                                        <b>
                                                            {Math.max(
                                                                0,
                                                                conversionRate - minimumDetectableChange
                                                            ).toFixed()}
                                                            % -{' '}
                                                            {Math.min(
                                                                100,
                                                                conversionRate + minimumDetectableChange
                                                            ).toFixed()}
                                                            %
                                                        </b>
                                                    </div>
                                                </Col>
                                            </Row>
                                        </Card>
                                        <Collapse>
                                            <Collapse.Panel
                                                header={
                                                    <div
                                                        style={{
                                                            display: 'flex',
                                                            fontWeight: 'bold',
                                                            alignItems: 'center',
                                                        }}
                                                    >
                                                        <IconJavascript style={{ marginRight: 6 }} /> Javascript
                                                        integration instructions
                                                    </div>
                                                }
                                                key="js"
                                            >
                                                <JSSnippet
                                                    variants={['control', 'test']}
                                                    flagKey={newExperimentData?.feature_flag_key || ''}
                                                />
                                            </Collapse.Panel>
                                        </Collapse>
                                    </Col>
                                </Row>

                                <div>
                                    <Row className="person-selection">
                                        <Col>
                                            <div className="l3 mb">Person selection</div>
                                            <div className="text-muted">
                                                Select the persons who will participate in this experiment. We'll split
                                                all persons evenly in a control and experiment group.
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
                                                        Define the metric which you are trying to optimize. This is the
                                                        most important part of your experiment.
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
                                        <Button icon={<SaveOutlined />} type="primary" htmlType="submit">
                                            Save and preview
                                        </Button>
                                    </Row>
                                </div>
                            </div>
                        )}

                        {newExperimentCurrentPage === 1 && (
                            <div className="confirmation">
                                {newExperimentData?.description && (
                                    <Row>Description: {newExperimentData?.description}</Row>
                                )}
                                <Row className="mt">
                                    <Col span={12}>
                                        <div>Feature flag key: {newExperimentData?.feature_flag_key}</div>
                                        <div>Variants: 'control' and 'test'</div>
                                    </Col>
                                    <Col span={12}>
                                        <Collapse>
                                            <Collapse.Panel
                                                header={
                                                    <div
                                                        style={{
                                                            display: 'flex',
                                                            fontWeight: 'bold',
                                                            alignItems: 'center',
                                                        }}
                                                    >
                                                        <IconJavascript style={{ marginRight: 6 }} /> Javascript
                                                        integration instructions
                                                    </div>
                                                }
                                                key="js"
                                            >
                                                <JSSnippet
                                                    variants={['control', 'test']}
                                                    flagKey={newExperimentData?.feature_flag_key || ''}
                                                />
                                            </Collapse.Panel>
                                        </Collapse>
                                    </Col>
                                </Row>
                                <Row className="mt">
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
                    {experimentData.end_date && <Alert type="info" message="This experiment has ended" />}
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
                    {!experimentData.end_date ? (
                        <LemonButton onClick={() => endExperiment()}>End experiment</LemonButton>
                    ) : (
                        <div>Experiment ended {dayjs(experimentData.end_date)}</div>
                    )}
                </div>
            ) : (
                <div>Loading...</div>
            )}
        </>
    )
}

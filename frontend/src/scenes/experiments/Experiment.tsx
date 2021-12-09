import SaveOutlined from '@ant-design/icons/lib/icons/SaveOutlined'
import { Button, Carousel, Col, Form, Input, Row } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React, { useRef } from 'react'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'
import { PropertyFilter } from '~/types'
import './Experiment.scss'
import { experimentLogic } from './experimentLogic'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentLogic,
}

export function Experiment(): JSX.Element {
    const { user } = useValues(userLogic)
    const { newExperimentData, experimentId, experimentData, experimentResults } = useValues(experimentLogic)
    const { setNewExperimentData, createExperiment, createDraftExperiment } = useActions(experimentLogic)
    const carouselRef = useRef<any>(null)
    const handleNext = (): void => carouselRef.current.next()
    const handlePrev = (): void => carouselRef.current.prev()
    const [form] = Form.useForm()

    return experimentId === 'new' ? (
        <>
            <PageHeader title="New Experiment" />
            <Form
                name="new-experiment"
                layout="vertical"
                className="experiment-form"
                form={form}
                onFinish={(values) => setNewExperimentData(values)}
            >
                <Carousel ref={carouselRef}>
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
                            <Button icon={<SaveOutlined />} htmlType="submit" type="primary" onClick={handleNext}>
                                Save and continue
                            </Button>
                        </Form.Item>
                    </div>
                    <div>
                        <Form.Item label="Person selection">
                            <Form.Item name="filters">
                                <label>Select the users who will participate in this experiment.</label>
                                <div style={{ flex: 3, marginRight: 5 }}>
                                    <PropertyFilters
                                        endpoint="person"
                                        pageKey={'1234'}
                                        onChange={(personProperties) => {
                                            form.setFieldsValue({ filters: { properties: personProperties } })
                                        }}
                                        propertyFilters={[]}
                                        // onChange={(properties) => {
                                        //     onPropertyCriteriaChange({ properties })
                                        // }}
                                        // propertyFilters={group.properties}
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
                        <Form.Item className="text-right">
                            <Button icon={<SaveOutlined />} htmlType="submit" type="primary" onClick={handleNext}>
                                Save and preview
                            </Button>
                        </Form.Item>
                        <Button onClick={handlePrev}>Go back</Button>
                    </div>
                    {newExperimentData && (
                        <div className="confirmation">
                            <PageHeader title={newExperimentData.name} />
                            <div>{newExperimentData?.description}</div>
                            <div>Owner: {user?.first_name}</div>
                            <div>Feature flag key: {newExperimentData?.feature_flag_key}</div>
                            <Row>
                                <Col>
                                    <Row>Person allocation</Row>
                                    <Row>The following users will participate in the experiment</Row>
                                    <ul>
                                        {newExperimentData.filters?.properties?.map(
                                            (filter: PropertyFilter, idx: number) => (
                                                <li key={idx}>
                                                    Users with {filter.key} {filter.operator}{' '}
                                                    {Array.isArray(filter.value)
                                                        ? filter.value.map((val) => `${val}, `)
                                                        : filter.value}
                                                </li>
                                            )
                                        )}
                                    </ul>
                                </Col>
                            </Row>
                            <Button onClick={createDraftExperiment}>Save as draft</Button>
                            <Button type="primary" onClick={createExperiment}>
                                Save and launch
                            </Button>
                        </div>
                    )}
                </Carousel>
            </Form>
        </>
    ) : experimentData ? (
        <>
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
                        dashboardItemId: undefined,
                        filters: { ...experimentResults.filters, insight: 'FUNNELS', display: 'FunnelViz' },
                        cachedResults: experimentResults.funnel,
                        syncWithUrl: false,
                    }}
                >
                    <div>
                        <PageHeader title="Results" />
                        <div>Probability: {experimentResults.probability}</div>
                        <InsightContainer />
                    </div>
                </BindLogic>
            )}
        </>
    ) : (
        <div>Loading...</div>
    )
}

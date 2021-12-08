import SaveOutlined from '@ant-design/icons/lib/icons/SaveOutlined'
import { Button, Carousel, Col, Form, Input, Row } from 'antd'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React, { useRef } from 'react'
import { FunnelBarGraph } from 'scenes/funnels/FunnelBarGraph'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { FunnelSingleStepState } from 'scenes/insights/EmptyStates'
import { insightLogic } from 'scenes/insights/insightLogic'
import { userLogic } from 'scenes/userLogic'
import { PropertyFilter } from '~/types'
import './Experiment.scss'
import { experimentLogic } from './experimentLogic'

export function Experiment(): JSX.Element {
    const { user } = useValues(userLogic)
    const { experiment, funnelProps } = useValues(experimentLogic)
    const { setExperiment, createExperiment } = useActions(experimentLogic)
    const carouselRef = useRef<any>(null)
    const handleNext = (): void => carouselRef.current.next()
    const handlePrev = (): void => carouselRef.current.prev()
    const [form] = Form.useForm()

    const { isStepsEmpty, filterSteps, areFiltersValid } = useValues(funnelLogic(funnelProps))
    const { setFilters } = useActions(funnelLogic(funnelProps))

    return (
        <BindLogic logic={insightLogic} props={funnelProps}>
            <PageHeader title={experiment?.name || 'New Experiment'} />
            <Form
                name="new-experiment"
                layout="vertical"
                className="experiment-form"
                form={form}
                onFinish={(values) => setExperiment(values)}
            >
                <Carousel ref={carouselRef}>
                    <div>
                        <Form.Item label="Name" name="name">
                            <Input data-attr="experiment-name" className="ph-ignore-input" />
                        </Form.Item>
                        <Form.Item label="Feature flag key" name="feature-flag">
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
                        <Form.Item className="person-selection" label="Person selection">
                            <Form.Item name="person-selection">
                                <span className="text-muted">
                                    Select the persons who will participate in this experiment. We'll split all persons
                                    evenly in a control and experiment group.
                                </span>
                                <div style={{ flex: 3, marginRight: 5 }}>
                                    <PropertyFilters
                                        endpoint="person"
                                        pageKey={'1234'}
                                        onChange={(personProperties) => {
                                            form.setFieldsValue({ filters: { properties: personProperties } })
                                        }}
                                        propertyFilters={[]}
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
                                <span className="text-muted">
                                    Define the metric which you are trying to optimize. This is the most important part
                                    of your experiment.
                                </span>
                                <Row>
                                    <Col span={12}>
                                        {funnelProps.filters && (
                                            <ActionFilter
                                                filters={funnelProps.filters}
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
                                                    // ...groupsTaxonomicTypes,
                                                    TaxonomicFilterGroupType.Cohorts,
                                                    TaxonomicFilterGroupType.Elements,
                                                ]}
                                                rowClassName="action-filters-bordered"
                                            />
                                        )}
                                    </Col>
                                    <Col span={12}>
                                        {areFiltersValid ? <FunnelBarGraph /> : <FunnelSingleStepState />}
                                    </Col>
                                </Row>
                            </Form.Item>
                        </Form.Item>
                        <Form.Item className="text-right">
                            <Button icon={<SaveOutlined />} htmlType="submit" type="primary" onClick={handleNext}>
                                Save and preview
                            </Button>
                        </Form.Item>
                        <Button onClick={handlePrev}>Go back</Button>
                    </div>

                    <div className="confirmation">
                        <PageHeader title={experiment?.name || ''} />
                        <div>{experiment?.description}</div>
                        <div>Owner: {user?.first_name}</div>
                        <div>Feature flag key: {experiment?.feature_flag}</div>
                        <Row>
                            <Col>
                                <Row>Person allocation</Row>
                                <Row>The following users will participate in the experiment</Row>
                                <ul>
                                    {experiment?.filters?.properties?.map((property: PropertyFilter, idx: number) => (
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
                        <Button onClick={() => createExperiment(true)}>Save as draft</Button>
                        <Button type="primary" onClick={createExperiment}>
                            Save and launch
                        </Button>
                    </div>
                </Carousel>
            </Form>
        </BindLogic>
    )
}

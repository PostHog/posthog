import SaveOutlined from '@ant-design/icons/lib/icons/SaveOutlined'
import { Button, Carousel, Form, Input } from 'antd'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React, { useRef } from 'react'
import { userLogic } from 'scenes/userLogic'
import './Experiment.scss'
import { experimentLogic } from './experimentLogic'

export function Experiment(): JSX.Element {
    const { user } = useValues(userLogic)
    const { experiment } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)
    const carouselRef = useRef<any>(null)
    const handleNext = (): void => carouselRef.current.next()
    const handlePrev = (): void => carouselRef.current.prev()
    const [form] = Form.useForm()

    return (
        <>
            <PageHeader title="New Experiment" />
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
                        <Form.Item label="Person selection">
                            <label>Select the users who will participate in this experiment.</label>
                            <div style={{ flex: 3, marginRight: 5 }}>
                                <PropertyFilters
                                    endpoint="person"
                                    pageKey={'1234'}
                                    onChange={(personProperties) => {
                                        form.setFieldsValue({ personSelection: personProperties })
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
                        <Form.Item className="text-right">
                            <Button icon={<SaveOutlined />} htmlType="submit" type="primary" onClick={handleNext}>
                                Save and preview
                            </Button>
                        </Form.Item>
                        <Button onClick={handlePrev}>Go back</Button>
                    </div>
                    <div className="confirmation">
                        <PageHeader title={experiment?.name} />
                        <div>{experiment?.description}</div>
                        <div>Owner: {user?.first_name}</div>
                        <div>Feature flag key: {experiment?.feature_flag}</div>
                    </div>
                </Carousel>
            </Form>
        </>
    )
}

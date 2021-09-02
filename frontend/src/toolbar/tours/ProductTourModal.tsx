import { PlusOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { Button, Input, Modal, Row, Select } from 'antd'
import React from 'react'
import { cohortsModel } from '~/models/cohortsModel'
import { StepsTab } from '~/toolbar/tours/StepsTab'
import { toursLogic } from './toursLogic'
import { toolbarButtonLogic } from '../button/toolbarButtonLogic'

export function ProductTourModal(): JSX.Element {
    const { slide, params, onElementSelection, tourEnabled, stepElement } = useValues(toursLogic)
    const { setParams, setSlide } = useActions(toursLogic)
    const { cohorts } = useValues(cohortsModel)
    const { hideToursInfo } = useActions(toolbarButtonLogic)

    console.log('HELLOE', slide, stepElement)

    console.log(tourEnabled, onElementSelection)

    return (
        <Modal
            footer={
                <>
                    {slide > 0 && (
                        <Button onClick={() => setSlide(slide - 1)} type="primary">
                            Back
                        </Button>
                    )}
                    {slide !== 0 && (
                        <Button onClick={() => (slide === 3 ? null : setSlide(slide + 1))} type="primary">
                            {slide === 3 ? 'Save and close' : 'Next'}
                        </Button>
                    )}
                </>
            }
            visible={tourEnabled && !onElementSelection}
            onCancel={hideToursInfo}
            destroyOnClose
            title={<div style={{ fontSize: 20 }}>{slide === 0 ? 'Product tours' : 'Create a product tour'}</div>}
        >
            {slide === 0 && (
                <>
                    {/* <PageHeader title="Product tours" /> */}
                    <Row style={{ marginBottom: 16 }}>
                        Improve discoverability by guiding users through a tour of features.
                    </Row>
                    <div
                        style={{
                            backgroundColor: '#fbfbfb',
                            padding: 24,
                            border: '2px solid var(--border)',
                            borderRadius: 10,
                            textAlign: 'center',
                        }}
                    >
                        <Row style={{ paddingBottom: 12, justifyContent: 'center' }}>No product tours found</Row>
                        <Button type="primary" icon={<PlusOutlined />} onClick={() => setSlide(slide + 1)}>
                            Create a product tour
                        </Button>
                    </div>
                </>
            )}
            {slide !== 0 && (
                <>
                    <Row style={{ justifyContent: 'space-evenly', paddingBottom: 16 }}>
                        <div
                            style={{
                                textAlign: 'center',
                                flex: 1,
                                padding: '4px 24px',
                                fontWeight: 600,
                                marginRight: 3,
                                borderRadius: '10px 0px 0px 10px',
                                backgroundColor: 'var(--border)',
                                color: `${slide === 1 ? 'black' : '#999999'}`,
                            }}
                        >
                            1. Info
                        </div>
                        <div
                            style={{
                                textAlign: 'center',
                                flex: 1,
                                padding: '4px 24px',
                                fontWeight: 600,
                                marginRight: 3,
                                backgroundColor: 'var(--border)',
                                color: `${slide === 2 ? 'black' : '#999999'}`,
                            }}
                        >
                            2. Audience
                        </div>
                        <div
                            style={{
                                textAlign: 'center',
                                flex: 1,
                                padding: '4px 24px',
                                fontWeight: 600,
                                borderRadius: '0px 10px 10px 0px',
                                backgroundColor: 'var(--border',
                                color: `${slide === 3 ? 'black' : '#999999'}`,
                            }}
                        >
                            3. Steps
                        </div>
                    </Row>
                </>
            )}
            {slide === 1 && (
                <div>
                    <Row>
                        <span style={{ paddingBottom: 4 }}>Tour name</span>
                        <Input
                            value={params.name}
                            onChange={(e) => setParams({ name: e.target.value })}
                            placeholder="An internal name to reference this tour. Eg: Onboarding flow"
                        />
                    </Row>
                    <Row>
                        <span style={{ paddingTop: 12, paddingBottom: 4 }}>Start point</span>
                        <Input defaultValue={window.location.href} />
                    </Row>
                </div>
            )}
            {slide === 2 && (
                <>
                    <Row style={{ fontWeight: 500, paddingBottom: 8 }}>Audience</Row>
                    <Select
                        onChange={(cohort: number | string) => setParams({ cohort })}
                        style={{ width: '100%', marginBottom: 12 }}
                        placeholder="Select a cohort"
                    >
                        {cohorts.map((cohort) => (
                            <Select.Option key={cohort.id} value={cohort.id}>
                                {cohort.name}
                            </Select.Option>
                        ))}
                    </Select>
                    <Row>
                        <Button icon={<PlusOutlined />}>New cohort</Button>
                    </Row>
                </>
            )}
            {slide === 3 && <StepsTab />}
        </Modal>
    )
}

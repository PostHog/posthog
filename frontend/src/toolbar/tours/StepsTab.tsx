import React, { useEffect, useState } from 'react'
import { Col, Collapse, Input, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { toursLogic } from '~/toolbar/tours/toursLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { HighlightOutlined } from '@ant-design/icons'
import { TourStepType, TourType } from '~/toolbar/types'

const getCurrentStep = (params: Partial<TourType>): TourStepType | undefined => {
    if ((params?.steps ?? []).length < 1) {
        return undefined
    }
    const steps = params.steps as TourStepType[]
    return steps[steps.length - 1]
}

export function StepsTab(): JSX.Element {
    const { setElementSelection, editStep } = useActions(toursLogic)
    const { params, stepElement } = useValues(toursLogic)
    // const { params: stepParams } = useValues(stepsTabLogic)
    // const { setParams: setStepParams } = useActions(stepsTabLogic)
    const { enableInspect } = useActions(elementsLogic)

    const currentStep = getCurrentStep(params)

    const [activeKey, setActiveKey] = useState([!!getCurrentStep(params)?.type ? '2' : '1'])

    useEffect(() => {
        if (!!currentStep?.type && !!stepElement) {
            setActiveKey(['2'])
        }
    }, [currentStep?.type, stepElement])

    console.log('STEPS', params, stepElement)

    return (
        <div>
            {params?.steps ? (
                params.steps.map((step, i) => (
                    <div
                        key={i}
                        style={{
                            borderRadius: '10px 0px 0px 10px',
                            backgroundColor: 'var(--border)',
                        }}
                    >
                        {step}
                    </div>
                ))
            ) : (
                <div>
                    <Collapse defaultActiveKey={['1']} activeKey={activeKey}>
                        <Collapse.Panel showArrow={false} header="Type" key="1">
                            <Row align="middle" gutter={16} justify="center" wrap={false}>
                                <Col
                                    style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}
                                    onClick={() => {
                                        editStep({ ...currentStep, type: 'Tooltip' })
                                        setElementSelection(true)
                                        enableInspect()
                                    }}
                                >
                                    <div
                                        style={{
                                            borderRadius: 10,
                                            borderColor: 'var(--border)',
                                            borderWidth: 2,
                                            borderStyle: 'solid',
                                            padding: 10,
                                            marginBottom: 5,
                                            cursor: 'pointer',
                                        }}
                                    >
                                        <HighlightOutlined style={{ fontSize: '3rem' }} />
                                    </div>
                                    <span style={{ fontWeight: 500, color: 'var(--primary)' }}>Tooltip</span>
                                </Col>
                                <Col style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                                    <div
                                        style={{
                                            borderRadius: 10,
                                            borderColor: 'var(--border)',
                                            borderWidth: 2,
                                            borderStyle: 'solid',
                                            padding: 10,
                                            marginBottom: 5,
                                            cursor: 'pointer',
                                        }}
                                    >
                                        <HighlightOutlined style={{ fontSize: '3rem' }} />
                                    </div>
                                    <span style={{ fontWeight: 500, color: 'var(--primary)' }}>Modal</span>
                                </Col>
                                <Col style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                                    <div
                                        style={{
                                            borderRadius: 10,
                                            borderColor: 'var(--border)',
                                            borderWidth: 2,
                                            borderStyle: 'solid',
                                            padding: 10,
                                            marginBottom: 5,
                                            cursor: 'pointer',
                                        }}
                                    >
                                        <HighlightOutlined style={{ fontSize: '3rem' }} />
                                    </div>
                                    <span style={{ fontWeight: 500, color: 'var(--primary)' }}>Beacon</span>
                                </Col>
                            </Row>
                        </Collapse.Panel>
                        <Collapse.Panel showArrow={false} header="Content" key="2">
                            <Row style={{ fontWeight: 500, paddingBottom: 8 }}>Tooltip title</Row>
                            <Input
                                value={currentStep?.tooltip_title}
                                onChange={(e) => setStepParams({ tooltip_title: e.target.value })}
                                placeholder="Check out this feature!"
                            />
                            <Row style={{ fontWeight: 500, paddingBottom: 8, paddingTop: 12 }}>Tooltip text</Row>
                            <Input.TextArea
                                value={currentStep?.tooltip_text}
                                onChange={(e) => setStepParams({ tooltip_text: e.target.value })}
                                placeholder="Here's how this works."
                            />
                            <span style={{ fontSize: '0.7rem', color: 'rgba(0, 0, 0, 0.5)' }}>Supports HTML</span>
                        </Collapse.Panel>
                    </Collapse>
                </div>
            )}
        </div>
    )
}

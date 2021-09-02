import React, { useEffect, useState } from 'react'
import { Button, Col, Collapse, Input, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { toursLogic } from '~/toolbar/tours/toursLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { HighlightOutlined, AlignCenterOutlined } from '@ant-design/icons'
import { TourStepType, TourType } from '~/toolbar/types'

const getCurrentStep = (params: Partial<TourType>): TourStepType | undefined => {
    if ((params?.steps ?? []).length < 1) {
        return undefined
    }
    const steps = params.steps as TourStepType[]
    return steps.find((s) => s?.is_new_step)
}

export function StepsTab(): JSX.Element {
    const { setElementSelection, editStep } = useActions(toursLogic)
    const { params } = useValues(toursLogic)
    const { enableInspect } = useActions(elementsLogic)

    const currentStep = getCurrentStep(params)

    const [activeKey, setActiveKey] = useState([!!getCurrentStep(params)?.type ? '2' : '1'])

    useEffect(() => {
        if (!!currentStep?.type && !!currentStep?.html_el) {
            setActiveKey(['2'])
        } else {
            setActiveKey(['1'])
        }
    }, [currentStep])

    return (
        <div>
            {params?.steps &&
                params.steps.map((step, i) => {
                    if (step?.is_completed) {
                        return (
                            <div
                                key={i}
                                style={{
                                    borderRadius: 6,
                                    padding: 8,
                                    backgroundColor: 'var(--border)',
                                    marginTop: 8,
                                }}
                            >
                                <Row style={{ alignItems: 'center' }}>
                                    <AlignCenterOutlined />
                                    <span
                                        style={{
                                            color: 'var(--primary)',
                                            fontWeight: 700,
                                            paddingLeft: 8,
                                        }}
                                    >
                                        Step {i + 1}
                                    </span>
                                </Row>
                            </div>
                        )
                    }
                    return <></>
                })}
            <div>
                <Collapse defaultActiveKey={['1']} activeKey={activeKey} style={{ marginTop: 10 }}>
                    <Collapse.Panel
                        showArrow={false}
                        header={`Type${currentStep?.html_el ? ` ∙ ${currentStep?.html_el}` : ''}`}
                        key="1"
                    >
                        <Row align="middle" gutter={16} justify="center" wrap={false}>
                            <Col
                                style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}
                                onClick={() => {
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
                            onChange={(e) => editStep({ id: currentStep?.id, tooltip_title: e.target.value })}
                            placeholder="Check out this feature!"
                        />
                        <Row style={{ fontWeight: 500, paddingBottom: 8, paddingTop: 12 }}>Tooltip text</Row>
                        <Input.TextArea
                            value={currentStep?.tooltip_text}
                            onChange={(e) => editStep({ id: currentStep?.id, tooltip_text: e.target.value })}
                            placeholder="Here's how this works."
                        />
                        <span style={{ fontSize: '0.7rem', color: 'rgba(0, 0, 0, 0.5)' }}>Supports HTML</span>
                    </Collapse.Panel>
                </Collapse>
                <Row justify="end">
                    <Button
                        type="primary"
                        style={{ marginTop: 5 }}
                        onClick={() => {
                            editStep({ id: currentStep?.id, is_completed: true, is_new_step: false })
                        }}
                    >
                        Save step
                    </Button>
                </Row>
            </div>
        </div>
    )
}

import React, { useEffect, useState } from 'react'
import { Col, Collapse, Input, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { toursLogic } from '~/toolbar/tours/toursLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { stepsTabLogic } from '~/toolbar/tours/stepsTabLogic'
import { HighlightOutlined } from '@ant-design/icons'

export function StepsTab(): JSX.Element {
    const { setElementSelection } = useActions(toursLogic)
    const { params, stepElement } = useValues(toursLogic)
    const { params: stepParams } = useValues(stepsTabLogic)
    const { setParams: setStepParams } = useActions(stepsTabLogic)
    const { enableInspect } = useActions(elementsLogic)

    const [activeKey, setActiveKey] = useState([!!stepParams?.type ? '2' : '1'])

    useEffect(() => {
        if (!!stepParams?.type && !!stepElement) {
            setActiveKey(['2'])
        }
    }, [stepParams?.type, stepElement])

    console.log('STEPS', stepParams, stepElement)

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
                                        setStepParams({ type: 'Tooltip' })
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
                                value={stepParams.tooltip_title}
                                onChange={(e) => setStepParams({ tooltip_title: e.target.value })}
                                placeholder="Check out this feature!"
                            />
                            <Row style={{ fontWeight: 500, paddingBottom: 8, paddingTop: 12 }}>Tooltip text</Row>
                            <Input.TextArea
                                value={stepParams.tooltip_text}
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

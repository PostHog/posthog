import React from 'react'
import { Col, Card, Row } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'

export function CardContainer(props) {
    return (
        <Col>
            <Card
                headStyle={{ minHeight: 60 }}
                title={
                    <Row align="middle" data-attr="wizard-step-counter">
                        {props.index !== 0 && (
                            <ArrowLeftOutlined className="clickable" onClick={() => props.onBack()}></ArrowLeftOutlined>
                        )}
                        {`Step ${props.index + 1} ${props.totalSteps ? 'of' : ''} ${
                            props.totalSteps ? props.totalSteps : ''
                        }`}
                    </Row>
                }
                className="card"
                style={{ width: '65vw', maxHeight: '70vh', overflow: 'scroll' }}
            >
                {props.children}
            </Card>

            {props.nextButton && (
                <Card
                    data-attr="wizard-continue-button"
                    className="card big-button"
                    style={{
                        marginTop: 20,
                        width: '65vw',
                        height: 70,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        borderRadius: 5,
                        cursor: 'pointer',
                        backgroundColor: '#007bff',
                    }}
                    onClick={props.onSubmit}
                >
                    <span style={{ fontWeight: 500, fontSize: 18, color: 'white' }}>Continue</span>
                </Card>
            )}
        </Col>
    )
}

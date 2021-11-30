import React from 'react'
import { Col, Card, Row } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'

export function CardContainer({
    index,
    totalSteps,
    onBack,
    children,
    nextButton,
    onSubmit,
}: {
    index: number
    totalSteps?: number
    onBack?: () => void
    children: React.ReactNode
    nextButton?: boolean
    onSubmit?: () => void
}): JSX.Element {
    return (
        <Col>
            <Card
                headStyle={{ minHeight: 60 }}
                title={
                    <Row align="middle" data-attr="wizard-step-counter">
                        {index !== 0 && (
                            <ArrowLeftOutlined
                                className="button-border clickable"
                                style={{ marginRight: 4 }}
                                onClick={onBack}
                            />
                        )}
                        {`Step ${index + 1} ${totalSteps ? 'of' : ''} ${totalSteps ? totalSteps : ''}`}
                    </Row>
                }
                style={{ width: '65vw', maxHeight: '70vh', overflow: 'auto', border: '1px solid var(--border)' }}
            >
                {children}
            </Card>

            {nextButton && (
                <div
                    data-attr="wizard-continue-button"
                    className="bg-primary"
                    role="button"
                    style={{
                        marginTop: 20,
                        width: '65vw',
                        height: 70,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        borderRadius: 5,
                        cursor: 'pointer',
                    }}
                    onClick={onSubmit}
                >
                    <span style={{ fontWeight: 500, fontSize: 18, color: 'white' }}>Continue</span>
                </div>
            )}
        </Col>
    )
}

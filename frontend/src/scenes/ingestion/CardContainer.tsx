import React from 'react'
import { Col, Card, Row } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { ingestionLogic } from './ingestionLogic'
import { useValues } from 'kea'
import { PanelHeader } from './panels/PanelComponents'
import './panels/Panels.scss'

export function CardContainer({
    index,
    onBack,
    children,
    nextButton,
    onSubmit,
}: {
    index: number
    onBack?: () => void
    children: React.ReactNode
    nextButton?: boolean
    onSubmit?: () => void
}): JSX.Element {
    const { onboarding1 } = useValues(ingestionLogic)

    return (
        <Col className="ingestion-card-container">
            <Card
                headStyle={{ border: 'none', paddingBottom: 0 }}
                title={
                    <Row align="middle" data-attr="wizard-step-counter">
                        {index !== 0 && (
                            <ArrowLeftOutlined
                                className="button-border clickable"
                                style={{ marginRight: 4 }}
                                onClick={onBack}
                            />
                        )}
                        <PanelHeader index={index} />
                    </Row>
                }
                style={{
                    position: 'relative',
                    maxWidth: '65vw',
                    maxHeight: '70vh',
                    overflow: 'auto',
                    border: '1px solid var(--border)',
                }}
            >
                {children}
            </Card>
            {!onboarding1 && nextButton && (
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

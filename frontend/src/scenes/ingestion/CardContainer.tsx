import React from 'react'
import { Row } from 'antd'
import { ingestionLogic } from './ingestionLogic'
import { useValues } from 'kea'
import { PanelFooter, PanelHeader } from './panels/PanelComponents'
import './panels/Panels.scss'

export function CardContainer({
    index,
    children,
    showFooter,
    onSubmit,
}: {
    index: number
    onBack?: () => void
    children: React.ReactNode
    showFooter?: boolean
    onSubmit?: () => void
}): JSX.Element {
    const { onboarding1 } = useValues(ingestionLogic)

    return (
        <div className="ingestion-card-container">
            <Row align="middle" data-attr="wizard-step-counter">
                <PanelHeader index={index} />
            </Row>
            {children}
            <div>
                {showFooter &&
                    (onboarding1 ? (
                        <PanelFooter />
                    ) : (
                        <div
                            data-attr="wizard-continue-button"
                            className="bg-primary"
                            role="button"
                            style={{
                                height: 70,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                borderRadius: 5,
                                cursor: 'pointer',
                                margin: 16,
                            }}
                            onClick={onSubmit}
                        >
                            <span style={{ fontWeight: 500, fontSize: 18, color: 'white' }}>Continue</span>
                        </div>
                    ))}
            </div>
        </div>
    )
}

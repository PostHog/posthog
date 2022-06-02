import React from 'react'
import { Row } from 'antd'
import { ingestionLogic } from './ingestionLogic'
import { useValues } from 'kea'
import { PanelFooter, PanelHeader } from './panels/PanelComponents'
import './panels/Panels.scss'
import { ArrowLeftOutlined } from '@ant-design/icons'

export function CardContainer({
    index,
    onBack,
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
    const { onboarding1, onboardingSidebarEnabled } = useValues(ingestionLogic)

    return (
        <div className="ingestion-card-container">
            {!onboardingSidebarEnabled && (
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
            )}
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

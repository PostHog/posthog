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
}: {
    index: number
    onBack?: () => void
    children: React.ReactNode
    showFooter?: boolean
}): JSX.Element {
    const { onboardingSidebarEnabled, isSmallScreen } = useValues(ingestionLogic)

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
            {onboardingSidebarEnabled && isSmallScreen && (
                <>
                    <ArrowLeftOutlined
                        className="button-border clickable"
                        style={{ marginRight: 'auto', color: 'var(--primary)' }}
                        onClick={onBack}
                    />
                </>
            )}
            {children}
            <div>{showFooter && <PanelFooter />}</div>
        </div>
    )
}

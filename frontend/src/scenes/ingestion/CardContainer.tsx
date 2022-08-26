import React from 'react'
import { ingestionLogic } from './ingestionLogic'
import { useValues } from 'kea'
import { PanelFooter, PanelHeader } from './panels/PanelComponents'
import './panels/Panels.scss'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { LemonButton } from '@posthog/lemon-ui'

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
    const { isSmallScreen } = useValues(ingestionLogic)

    return (
        <div>
            {!isSmallScreen ? (
                <div className="flex items-center" data-attr="wizard-step-counter">
                    {index !== 0 && (
                        <LemonButton className="mr-2" size="small" status="primary-alt" onClick={onBack}>
                            <ArrowLeftOutlined />
                        </LemonButton>
                    )}
                    <PanelHeader index={index} />
                </div>
            ) : (
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

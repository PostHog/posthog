import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Col, Row } from 'antd'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { API, mobileFrameworks, BACKEND, webFrameworks } from 'scenes/ingestion/constants'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { PanelSupport } from './PanelComponents'
import { LemonDivider } from 'lib/components/LemonDivider'

export function FrameworkPanel(): JSX.Element {
    const { setPlatform, setFramework } = useActions(ingestionLogic)
    const { platform, index, onboardingSidebarEnabled } = useValues(ingestionLogic)
    const frameworks = platform === BACKEND ? webFrameworks : mobileFrameworks

    return (
        <CardContainer index={index} onBack={() => setPlatform(null)}>
            <div style={{ maxWidth: 400 }}>
                <h1 className="ingestion-title">
                    {platform === BACKEND ? 'Choose the framework your app is built in' : 'Pick a mobile platform'}
                </h1>
                <p className="prompt-text">
                    We'll provide you with snippets that you can easily add to your codebase to get started!
                </p>
                <Col className="framework-panel">
                    {(Object.keys(frameworks) as (keyof typeof frameworks)[]).map((item) => (
                        <LemonButton
                            type="primary"
                            key={item}
                            data-attr={`select-framework-${item}`}
                            fullWidth
                            size="large"
                            center
                            className="mb-05"
                            onClick={() => setFramework(item)}
                        >
                            {frameworks[item]}
                        </LemonButton>
                    ))}
                    <Row justify="center" className="mt pb">
                        <p className="text-center mb-0 text-muted" style={{ fontSize: 16 }}>
                            Don't see your framework here?{' '}
                            <a onClick={() => setFramework(API)}>
                                <b>Continue with our HTTP API</b>
                            </a>
                        </p>
                    </Row>
                    {!onboardingSidebarEnabled && (
                        <>
                            <LemonDivider thick dashed />
                            <PanelSupport />
                        </>
                    )}
                </Col>
            </div>
        </CardContainer>
    )
}

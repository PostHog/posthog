import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Col, List, Row } from 'antd'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { API, mobileFrameworks, BACKEND, webFrameworks } from 'scenes/ingestion/constants'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'

export function FrameworkPanel(): JSX.Element {
    const { setPlatform, setFramework } = useActions(ingestionLogic)
    const { platform, index, onboarding1 } = useValues(ingestionLogic)
    const frameworks = platform === BACKEND ? webFrameworks : mobileFrameworks

    return (
        <CardContainer
            index={index}
            onBack={() => {
                setPlatform(null)
            }}
        >
            {onboarding1 ? (
                <div style={{ maxWidth: 400, marginLeft: 24, marginRight: 24 }}>
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
                                center
                                className="ingestion-btn"
                                onClick={() => setFramework(item)}
                            >
                                {frameworks[item]}
                            </LemonButton>
                        ))}
                        <Row justify="center" className="mt">
                            <p className="text-center mb-0" style={{ fontSize: 16 }}>
                                Don't see your framework here?{' '}
                                <a onClick={() => setFramework(API)}>
                                    <b>Continue with our HTTP API</b>
                                </a>
                            </p>
                        </Row>
                    </Col>
                </div>
            ) : (
                <>
                    <p className="prompt-text">
                        We'll provide you with snippets that you can easily add to your codebase to get started!
                    </p>
                    <Col className="framework-panel">
                        <List
                            style={{ width: '100%' }}
                            bordered
                            dataSource={Object.keys(frameworks) as (keyof typeof frameworks)[]}
                            renderItem={(item) => (
                                <List.Item
                                    className="selectable-item"
                                    data-attr={'select-framework-' + item}
                                    onClick={() => setFramework(item)}
                                    key={item}
                                >
                                    {frameworks[item]}
                                </List.Item>
                            )}
                        />
                        <Row align="middle" style={{ float: 'right', marginTop: 8 }}>
                            <p>
                                Don't see a language/platform/framework here?
                                <b className="button-border clickable" onClick={() => setFramework(API)}>
                                    Continue with our HTTP API
                                </b>
                            </p>
                        </Row>
                    </Col>
                </>
            )}
        </CardContainer>
    )
}

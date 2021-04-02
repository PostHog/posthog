import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { List, Row } from 'antd'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { API, mobileFrameworks, BACKEND, webFrameworks } from 'scenes/ingestion/constants'

export function FrameworkPanel(): JSX.Element {
    const { setPlatform, setFramework } = useActions(ingestionLogic)
    const { platform, index, totalSteps } = useValues(ingestionLogic)
    const frameworks = platform === BACKEND ? webFrameworks : mobileFrameworks

    return (
        <CardContainer
            index={index}
            totalSteps={totalSteps}
            onBack={() => {
                setPlatform(null)
            }}
        >
            <p className="prompt-text">
                Choose the framework your app is built in. We'll provide you with snippets that you can easily add to
                your codebase to get started!
            </p>
            <Row>
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
            </Row>
            <Row align="middle" style={{ float: 'right', marginTop: 8 }}>
                Don't see a language/platform/framework here?
                <b style={{ marginLeft: 5 }} className="button-border clickable" onClick={() => setFramework(API)}>
                    Continue with our HTTP API
                </b>
            </Row>
        </CardContainer>
    )
}

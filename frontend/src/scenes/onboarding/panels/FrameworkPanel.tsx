import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/onboarding/CardContainer'
import { List, Row } from 'antd'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { API, mobileFrameworks, WEB, webFrameworks } from 'scenes/onboarding/constants'

export function FrameworkPanel(): JSX.Element {
    const { setCustomEvent, setPlatformType, setFramework } = useActions(onboardingLogic)
    const { platformType, index, totalSteps } = useValues(onboardingLogic)
    const frameworks = platformType === WEB ? webFrameworks : mobileFrameworks

    return (
        <CardContainer
            index={index}
            totalSteps={totalSteps}
            onBack={() => {
                platformType === WEB ? setCustomEvent(false) : setPlatformType(null)
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

import React from 'react'
import { Row, List, Button } from 'antd'
import './OnboardingWizard.scss'

import { CardContainer } from './CardContainer'
import { VerificationPanel } from 'scenes/onboarding/VerificationPanel'
import { AutocapturePanel } from 'scenes/onboarding/AutocapturePanel'
import { InstructionsPanel } from 'scenes/onboarding/InstructionsPanel'
import { API, MOBILE, mobileFrameworks, platformTypes, WEB, webFrameworks } from 'scenes/onboarding/constants'
import { PlatformType } from 'scenes/onboarding/types'
import { useActions, useValues } from 'kea'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'

export function OnboardingContainer({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div
            className="background"
            style={{ display: 'flex', height: '100vh', width: '100vw', alignItems: 'center', justifyContent: 'center' }}
        >
            {children}
        </div>
    )
}

export default function OnboardingWizard(): JSX.Element {
    const { platformType, framework, customEvent, verify, index, totalSteps } = useValues(onboardingLogic)
    const { setPlatformType, setFramework, setCustomEvent } = useActions(onboardingLogic)

    if (verify) {
        return (
            <OnboardingContainer>
                <VerificationPanel />
            </OnboardingContainer>
        )
    }

    if (framework) {
        return (
            <OnboardingContainer>
                <InstructionsPanel />
            </OnboardingContainer>
        )
    }

    if (!platformType) {
        return (
            <OnboardingContainer>
                <CardContainer index={index}>
                    <h1>Welcome to PostHog</h1>
                    <p className="prompt-text">
                        Let's get you up and running with PostHog! What type of platform is your app? (You can connect
                        to multi-deployments later)
                    </p>
                    <Row>
                        {platformTypes.map((type) => (
                            <Button
                                type="primary"
                                data-attr={'select-platform-' + type}
                                key={type}
                                style={{ marginRight: 10 }}
                                onClick={() => setPlatformType(type as PlatformType)}
                            >
                                {type}
                            </Button>
                        ))}
                    </Row>
                </CardContainer>
            </OnboardingContainer>
        )
    }

    if (platformType === WEB && !customEvent) {
        return (
            <OnboardingContainer>
                <AutocapturePanel />
            </OnboardingContainer>
        )
    }

    if (platformType === MOBILE || (platformType === WEB && customEvent)) {
        const frameworks = platformType === WEB ? webFrameworks : mobileFrameworks

        return (
            <OnboardingContainer>
                <CardContainer
                    index={index}
                    totalSteps={totalSteps}
                    onBack={() => {
                        platformType === WEB ? setCustomEvent(false) : setPlatformType(null)
                    }}
                >
                    <p className="prompt-text">
                        Choose the framework your app is built in. We'll provide you with snippets that you can easily
                        add to your codebase to get started!
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
                        <b
                            style={{ marginLeft: 5 }}
                            className="button-border clickable"
                            onClick={() => setFramework(API)}
                        >
                            Continue with our HTTP API
                        </b>
                    </Row>
                </CardContainer>
            </OnboardingContainer>
        )
    }

    return <></>
}

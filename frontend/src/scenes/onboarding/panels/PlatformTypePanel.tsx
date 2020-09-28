import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/onboarding/CardContainer'
import { Button, Row } from 'antd'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { platformTypes } from 'scenes/onboarding/constants'
import { PlatformType } from 'scenes/onboarding/types'

export function PlatformTypePanel(): JSX.Element {
    const { setPlatformType } = useActions(onboardingLogic)
    const { index } = useValues(onboardingLogic)

    return (
        <CardContainer index={index}>
            <h1>Welcome to PostHog</h1>
            <p className="prompt-text">
                Let's get you up and running with PostHog! What type of platform is your app? (You can connect to
                multi-deployments later)
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
    )
}

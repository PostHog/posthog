import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Button, Row } from 'antd'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { platforms } from 'scenes/ingestion/constants'
import { PlatformType } from 'scenes/ingestion/types'

export function PlatformPanel(): JSX.Element {
    const { setPlatform } = useActions(ingestionLogic)
    const { index } = useValues(ingestionLogic)

    return (
        <CardContainer index={index}>
            <h1>Welcome to PostHog</h1>
            <p className="prompt-text">
                Let's get you up and running with PostHog! What type of platform is your app? (You can connect to
                multi-deployments later)
            </p>
            <Row>
                {platforms.map((platform) => (
                    <Button
                        type="primary"
                        data-attr={'select-platform-' + platform}
                        key={platform}
                        style={{ marginRight: 10 }}
                        onClick={() => setPlatform(platform as PlatformType)}
                    >
                        {platform}
                    </Button>
                ))}
            </Row>
        </CardContainer>
    )
}

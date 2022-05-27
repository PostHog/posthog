import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Button, Col, Row } from 'antd'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { THIRD_PARTY, BOOKMARKLET, platforms } from 'scenes/ingestion/constants'
import { PlatformType } from 'scenes/ingestion/types'
import { LemonButton } from 'lib/components/LemonButton'
import './Panels.scss'
import { PanelSupport } from './PanelComponents'
import { LemonDivider } from 'lib/components/LemonDivider'

export function PlatformPanel(): JSX.Element {
    const { setPlatform } = useActions(ingestionLogic)
    const { index, onboarding1, onboardingSidebarEnabled } = useValues(ingestionLogic)

    return (
        <>
            {onboarding1 ? (
                <div className="welcome-panel">
                    <h1 className="ingestion-title">Welcome to PostHog</h1>
                    <p>
                        First things first, where do you want to send events from? You can always instrument more
                        sources later.
                    </p>
                    <LemonDivider thick dashed style={{ marginTop: 24, marginBottom: 24 }} />
                    <Col style={{ marginBottom: 16 }}>
                        {platforms.map((platform) => (
                            <LemonButton
                                key={platform}
                                fullWidth
                                center
                                size="large"
                                type="primary"
                                className="mb-05"
                                onClick={() => setPlatform(platform)}
                            >
                                {platform}
                            </LemonButton>
                        ))}
                        <LemonButton
                            onClick={() => setPlatform(THIRD_PARTY)}
                            fullWidth
                            center
                            size="large"
                            className="mb-05"
                            type="primary"
                        >
                            {THIRD_PARTY}
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="large"
                            fullWidth
                            center
                            onClick={() => setPlatform(BOOKMARKLET)}
                        >
                            {BOOKMARKLET}
                        </LemonButton>
                    </Col>
                    {!onboardingSidebarEnabled && <PanelSupport />}
                </div>
            ) : (
                <CardContainer index={index}>
                    <h1>Welcome to PostHog</h1>
                    <p className="prompt-text">
                        Let's get you up and running with PostHog! What type of platform is your app? (You can connect
                        to multi-deployments later)
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
            )}
        </>
    )
}

import React from 'react'
import { useActions, useValues } from 'kea'
import { CardContainer } from 'scenes/ingestion/CardContainer'
import { Button, Col, Row } from 'antd'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { IMPORT, platforms } from 'scenes/ingestion/constants'
import { PlatformType } from 'scenes/ingestion/types'
import { LemonButton } from 'lib/components/LemonButton'
import posthogLogo from 'public/posthog-logo.png'
import { Link } from 'lib/components/Link'
import './Panels.scss'

export function PlatformPanel(): JSX.Element {
    const { setPlatform } = useActions(ingestionLogic)
    const { index, onboarding1 } = useValues(ingestionLogic)

    return (
        <>
            {onboarding1 ? (
                <div style={{ width: '30vw' }}>
                    <Row justify="center">
                        <img src={posthogLogo} style={{ width: 157, height: 30 }} />
                    </Row>
                    <div className="welcome-panel">
                        <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 8 }}>Welcome to PostHog</h1>
                        <p className="fw-500">
                            Let's get you up and running with PostHog! What type of platform is your app? Migrating from
                            another analytics service? Try one of our plugins or integrations to ingest data.
                        </p>
                        <Col>
                            {platforms.map((platform) => (
                                <LemonButton
                                    key={platform}
                                    fullWidth
                                    center
                                    type="primary"
                                    style={{ marginBottom: 8, background: 'black' }}
                                >
                                    {platform}
                                </LemonButton>
                            ))}
                            <LemonButton
                                fullWidth
                                center
                                type="primary"
                                style={{ marginBottom: 8, background: 'black' }}
                            >
                                {IMPORT}
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                fullWidth
                                center
                                style={{ color: 'black', borderColor: 'black' }}
                            >
                                Just exploring?
                            </LemonButton>
                        </Col>
                        <Row justify="center" className="visit-support">
                            <p style={{ marginBottom: 0 }}>
                                Have questions? <Link>Visit support</Link>
                            </p>
                        </Row>
                    </div>
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

import { Col, Row } from 'antd'
import { useValues, useActions } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import React from 'react'
import { CardContainer } from '../CardContainer'
import { ingestionLogic } from '../ingestionLogic'
import { Segment } from './ThirdPartyIcons'
import './Panels.scss'

export function ThirdPartyPanel(): JSX.Element {
    const { index } = useValues(ingestionLogic)
    const { setPlatform, setVerify } = useActions(ingestionLogic)

    const thirdPartyDataSources = [
        { name: 'Segment', type: 'integration', icon: <Segment /> },
        {
            name: 'Rudderstack',
            type: 'integration',
            icon: (
                <img
                    style={{ height: 36, width: 36 }}
                    src={'https://raw.githubusercontent.com/rudderlabs/rudderstack-posthog-plugin/main/logo.png'}
                />
            ),
        },
        {
            name: 'Redshift',
            type: 'plugin',
            icon: (
                <img
                    style={{ height: 48, width: 48 }}
                    src={'https://raw.githubusercontent.com/PostHog/posthog-redshift-import-plugin/main/logo.png'}
                />
            ),
        },
    ]

    return (
        <CardContainer
            index={index}
            showFooter={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setPlatform(null)}
        >
            <div style={{ paddingLeft: 24, paddingRight: 24 }}>
                <h1 className="ingestion-title">Set up apps</h1>
                {thirdPartyDataSources.map((source) => (
                    <div
                        key={source.name}
                        style={{
                            minWidth: 600,
                            border: '2px solid var(--border-light)',
                            borderRadius: 4,
                            padding: 16,
                            marginBottom: 8,
                        }}
                    >
                        <Row align="middle" justify="space-between">
                            <Row align="middle">
                                {source.icon}
                                <Col className="ml-05">
                                    <h3 className="mb-0">{source.name} Import</h3>
                                    <p className="mb-0 text-muted">Send events from {source.name} into PostHog</p>
                                </Col>
                            </Row>
                            <Row>
                                <LemonButton className="mr-05" type="secondary">
                                    About
                                </LemonButton>
                                <LemonButton type="primary" center>
                                    Configure
                                </LemonButton>
                            </Row>
                        </Row>
                    </div>
                ))}
            </div>
        </CardContainer>
    )
}

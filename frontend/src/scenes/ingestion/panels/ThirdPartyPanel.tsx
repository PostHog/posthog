import { Col, Row } from 'antd'
import { useValues, useActions } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import React from 'react'
import { CardContainer } from '../CardContainer'
import { ingestionLogic } from '../ingestionLogic'
import './Panels.scss'
import { LemonModal } from 'lib/components/LemonModal'
import { thirdPartySources } from '../constants'
import { IconOpenInNew } from 'lib/components/icons'
import { PanelSupport } from './PanelComponents'

export function ThirdPartyPanel(): JSX.Element {
    const { index } = useValues(ingestionLogic)
    const { setPlatform, setVerify, setInstructionsModal, setThirdPartySource } = useActions(ingestionLogic)

    return (
        <CardContainer
            index={index}
            showFooter={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setPlatform(null)}
        >
            <div style={{ paddingLeft: 24, paddingRight: 24 }}>
                <h1 className="ingestion-title">Set up apps</h1>
                {thirdPartySources.map((source, idx) => (
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
                                <LemonButton
                                    type="primary"
                                    center
                                    onClick={() => {
                                        setThirdPartySource(idx)
                                        setInstructionsModal(true)
                                    }}
                                >
                                    Configure
                                </LemonButton>
                            </Row>
                        </Row>
                    </div>
                ))}
            </div>
            <IntegrationInstructionsModal />
        </CardContainer>
    )
}

export function IntegrationInstructionsModal(): JSX.Element {
    const { instructionsModalOpen, thirdPartySource } = useValues(ingestionLogic)
    const { setInstructionsModal } = useActions(ingestionLogic)

    return (
        <LemonModal visible={instructionsModalOpen} onCancel={() => setInstructionsModal(false)}>
            {thirdPartySource?.name && (
                <div>
                    <h1>Integrate with {thirdPartySource.name} </h1>
                    <p>{thirdPartySource.name} is a </p>
                    <div style={{ borderTop: '2px dashed var(--border)' }}>
                        <div
                            style={{
                                padding: 20,
                                marginTop: 24,
                                marginBottom: 16,
                                backgroundColor: 'var(--bg-side)',
                                fontWeight: 500,
                            }}
                        >
                            The{' '}
                            <a
                                target="_blank"
                                href={`https://posthog.com/docs/integrate/third-party/${thirdPartySource.name}`}
                            >
                                official {thirdPartySource.name} docs page for the PostHog integration
                            </a>{' '}
                            provides a detailed overview of how to set up this integration.
                        </div>
                    </div>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        center
                        sideIcon={<IconOpenInNew style={{ color: 'var(--primary)' }} />}
                    >
                        Take me to {thirdPartySource.name}
                    </LemonButton>
                    <div style={{ borderBottom: '2px dashed var(--border)' }}>
                        <h3>Steps:</h3>
                        <ol className="pl">
                            <li>Complete the steps in the {thirdPartySource.name} integration.</li>
                            <li>
                                Close this step, and click <strong>continue</strong> to begin listening for events.
                            </li>
                        </ol>
                    </div>
                    <LemonButton fullWidth center type="primary">
                        Done
                    </LemonButton>
                </div>
            )}
            <PanelSupport />
        </LemonModal>
    )
}

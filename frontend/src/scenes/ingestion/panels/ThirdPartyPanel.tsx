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
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginInstallationType } from 'scenes/plugins/types'

export function ThirdPartyPanel(): JSX.Element {
    const { index } = useValues(ingestionLogic)
    const { setPlatform, setVerify, setInstructionsModal, setThirdPartySource, openThirdPartyPluginModal } = useActions(ingestionLogic)
    const { filteredUninstalledPlugins, installedPlugins } = useValues(pluginsLogic)
    const { installPlugin } = useActions(pluginsLogic)

    return (
        <CardContainer
            index={index}
            showFooter={true}
            onSubmit={() => setVerify(true)}
            onBack={() => setPlatform(null)}
        >
            <div style={{ paddingLeft: 24, paddingRight: 24 }}>
                <h1 className="ingestion-title">Set up apps</h1>
                {thirdPartySources.map((source, idx) => {
                    const installedThirdPartyPlugin = installedPlugins?.find(plugin => plugin.name.includes(source.name))
                    return (<div
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
                                    <h3 className="mb-0" style={{ fontWeight: 600, fontSize: 16 }}>{source.name} Import</h3>
                                    <p className="mb-0 text-muted">Send events from {source.name} into PostHog</p>
                                </Col>
                            </Row>
                            <Row>
                                <LemonButton className="mr-05" type="secondary" onClick={() => window.open(`https://posthog.com${source.type === "integration" ? `/docs/integrate/third-party/${source.name}` : `/integrations/${source.pluginName}`}`)}>
                                    About
                                </LemonButton>
                                {source.type === "integration" ? <LemonButton
                                    type="primary"
                                    center
                                    onClick={() => {
                                        setThirdPartySource(idx)
                                        setInstructionsModal(true)
                                    }}
                                >
                                    Configure
                                </LemonButton> : (
                                    <>
                                        {installedThirdPartyPlugin ?
                                            <LemonButton type="primary" onClick={() => {
                                                openThirdPartyPluginModal(installedThirdPartyPlugin)
                                            }}>
                                                Configure
                                            </LemonButton> :
                                            <LemonButton type="primary" onClick={() => {
                                                const pluginUrl = filteredUninstalledPlugins?.find(plugin => plugin.name.includes(source.name) && plugin.type === "data_in")?.url
                                                if (pluginUrl) {
                                                    installPlugin(pluginUrl, PluginInstallationType.Repository)
                                                }
                                            }}>
                                                Install
                                            </LemonButton>
                                        }
                                    </>
                                )}
                            </Row>
                        </Row>
                    </div>
                    )
                })}
            </div>
            <IntegrationInstructionsModal />
        </CardContainer>
    )
}

export function IntegrationInstructionsModal(): JSX.Element {
    const { instructionsModalOpen, thirdPartySource } = useValues(ingestionLogic)
    const { setInstructionsModal } = useActions(ingestionLogic)

    return (
        <>
            {thirdPartySource?.config_schema ? <PluginDrawer /> :
                <>
                    {thirdPartySource?.name && <LemonModal visible={instructionsModalOpen} onCancel={() => setInstructionsModal(false)} bodyStyle={{ padding: 40 }}>
                        {thirdPartySource.type === "integration" ? (
                            <div>
                                <p className="text-muted fw-500">Configure integration</p>
                                {thirdPartySource.icon}
                                <h1 className="ingestion-title">Integrate with {thirdPartySource.name} </h1>
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
                                            href={thirdPartySource.docsLink}
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
                                    onClick={() => window.open(`https://${thirdPartySource.name}.com`)}
                                    sideIcon={<IconOpenInNew style={{ color: 'var(--primary)' }} />}
                                >
                                    Take me to {thirdPartySource.name}
                                </LemonButton>
                                <div style={{ borderBottom: '2px dashed var(--border)', marginBottom: 24, marginTop: 16 }}>
                                    <h4>Steps:</h4>
                                    <ol className="pl">
                                        <li>Complete the steps in the {thirdPartySource.name} integration.</li>
                                        <li>
                                            Close this step and click <strong>continue</strong> to begin listening for events.
                                        </li>
                                    </ol>
                                </div>
                                <LemonButton fullWidth center type="primary" onClick={() => setInstructionsModal(false)}>
                                    Done
                                </LemonButton>
                            </div>
                        ) : <PluginDrawer />}
                        <PanelSupport />
                    </LemonModal>}
                </>
            }
        </>
    )
}

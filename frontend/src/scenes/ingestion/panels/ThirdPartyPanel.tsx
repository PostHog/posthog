import { Col, Row } from 'antd'
import { useValues, useActions } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import React from 'react'
import { CardContainer } from '../CardContainer'
import { ingestionLogic } from '../ingestionLogic'
import './Panels.scss'
import { LemonModal } from 'lib/components/LemonModal'
import { thirdPartySources, ThirdPartySourceType } from '../constants'
import { IconOpenInNew } from 'lib/components/icons'
import { PanelSupport } from './PanelComponents'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginInstallationType, PluginRepositoryEntryType, PluginTypeWithConfig } from 'scenes/plugins/types'
import { CodeSnippet } from '../frameworks/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { Link } from 'lib/components/Link'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export function ThirdPartyPanel(): JSX.Element {
    const { index } = useValues(ingestionLogic)
    const { setPlatform, setInstructionsModal, setThirdPartySource, openThirdPartyPluginModal } =
        useActions(ingestionLogic)
    const { filteredUninstalledPlugins, installedPlugins } = useValues(pluginsLogic)
    const { installPlugin } = useActions(pluginsLogic)
    const {
        reportIngestionThirdPartyAboutClicked,
        reportIngestionThirdPartyConfigureClicked,
        reportIngestionThirdPartyPluginInstalled,
    } = useActions(eventUsageLogic)

    return (
        <CardContainer index={index} showFooter={true} onBack={() => setPlatform(null)}>
            <div style={{ paddingLeft: 24, paddingRight: 24 }}>
                <h1 className="ingestion-title">Set up apps</h1>
                {thirdPartySources.map((source, idx) => {
                    const installedThirdPartyPlugin = installedPlugins?.find((plugin: PluginTypeWithConfig) =>
                        plugin.name.includes(source.name)
                    )
                    return (
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
                                        <h3
                                            className="mb-0"
                                            style={{
                                                fontWeight: 600,
                                                fontSize: 16,
                                                display: 'flex',
                                                alignItems: 'center',
                                            }}
                                        >
                                            {source.name} Import
                                            {source.labels?.map((label, labelIdx) => (
                                                <LemonTag
                                                    key={labelIdx}
                                                    type={label === 'beta' ? 'warning' : 'default'}
                                                    style={{ marginLeft: 8 }}
                                                >
                                                    {label}
                                                </LemonTag>
                                            ))}
                                        </h3>
                                        <p className="mb-0 text-muted">Send events from {source.name} into PostHog</p>
                                    </Col>
                                </Row>
                                <Row>
                                    <LemonButton
                                        className="mr-05"
                                        type="secondary"
                                        onClick={() => {
                                            window.open(
                                                `https://posthog.com${
                                                    source.type === ThirdPartySourceType.Integration
                                                        ? `/docs/integrate/third-party/${source.name}`
                                                        : `/integrations/${source.pluginName}`
                                                }`
                                            )
                                            reportIngestionThirdPartyAboutClicked(source.name)
                                        }}
                                    >
                                        About
                                    </LemonButton>
                                    {source.type === ThirdPartySourceType.Integration ? (
                                        <LemonButton
                                            type="primary"
                                            center
                                            onClick={() => {
                                                setThirdPartySource(idx)
                                                setInstructionsModal(true)
                                                reportIngestionThirdPartyConfigureClicked(source.name)
                                            }}
                                        >
                                            Configure
                                        </LemonButton>
                                    ) : (
                                        <>
                                            {installedThirdPartyPlugin ? (
                                                <LemonButton
                                                    type="primary"
                                                    onClick={() => {
                                                        openThirdPartyPluginModal(installedThirdPartyPlugin)
                                                        reportIngestionThirdPartyConfigureClicked(source.name)
                                                    }}
                                                >
                                                    Configure
                                                </LemonButton>
                                            ) : (
                                                <LemonButton
                                                    type="primary"
                                                    onClick={() => {
                                                        const pluginUrl = filteredUninstalledPlugins?.find(
                                                            (plugin) =>
                                                                plugin.name.includes(source.name) &&
                                                                plugin.type === PluginRepositoryEntryType.DataIn
                                                        )?.url
                                                        if (pluginUrl) {
                                                            installPlugin(pluginUrl, PluginInstallationType.Repository)
                                                        }
                                                        reportIngestionThirdPartyPluginInstalled(source.name)
                                                    }}
                                                >
                                                    Install
                                                </LemonButton>
                                            )}
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
    const { instructionsModalOpen, thirdPartyIntegrationSource, thirdPartyPluginSource } = useValues(ingestionLogic)
    const { setInstructionsModal } = useActions(ingestionLogic)
    const { currentTeam } = useValues(teamLogic)
    const { onboardingSidebarEnabled } = useValues(ingestionLogic)

    return (
        <>
            {thirdPartyPluginSource?.config_schema ? (
                <PluginDrawer />
            ) : (
                <>
                    {thirdPartyIntegrationSource?.name && (
                        <LemonModal
                            width="auto"
                            style={{ maxWidth: 600 }}
                            visible={instructionsModalOpen}
                            onCancel={() => setInstructionsModal(false)}
                            bodyStyle={{ padding: 40 }}
                        >
                            {thirdPartyIntegrationSource.type === ThirdPartySourceType.Integration ? (
                                <div>
                                    <p className="text-muted fw-500">Configure integration</p>
                                    {thirdPartyIntegrationSource.icon}
                                    <h1 className="ingestion-title">
                                        Integrate with {thirdPartyIntegrationSource.name}{' '}
                                    </h1>
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
                                            <p>
                                                The{' '}
                                                <a target="_blank" href={thirdPartyIntegrationSource.docsLink}>
                                                    official {thirdPartyIntegrationSource.name} docs page for the
                                                    PostHog integration
                                                </a>{' '}
                                                provides a detailed overview of how to set up this integration.
                                            </p>
                                            <b>PostHog Project API Key</b>
                                            <CodeSnippet copyDescription="project API key">
                                                {currentTeam?.api_token || ''}
                                            </CodeSnippet>
                                        </div>
                                    </div>
                                    <LemonButton
                                        type="secondary"
                                        fullWidth
                                        center
                                        onClick={() => window.open(`https://${thirdPartyIntegrationSource.name}.com`)}
                                        sideIcon={<IconOpenInNew style={{ color: 'var(--primary)' }} />}
                                    >
                                        Take me to {thirdPartyIntegrationSource.name}
                                    </LemonButton>
                                    <div
                                        style={{
                                            borderBottom: '2px dashed var(--border)',
                                            marginBottom: 24,
                                            marginTop: 16,
                                        }}
                                    >
                                        <h4>Steps:</h4>
                                        <ol className="pl">
                                            <li>
                                                Complete the steps in the {thirdPartyIntegrationSource.name}{' '}
                                                integration.
                                            </li>
                                            <li>
                                                Close this step and click <strong>continue</strong> to begin listening
                                                for events.
                                            </li>
                                        </ol>
                                        <p className="text-muted">
                                            <b>
                                                In order to access the session recordings feature, you'll also have to{' '}
                                                <Link to="/ingestion/web">integrate posthog js</Link>.
                                            </b>
                                        </p>
                                    </div>
                                    <LemonButton
                                        fullWidth
                                        center
                                        type="primary"
                                        onClick={() => setInstructionsModal(false)}
                                    >
                                        Done
                                    </LemonButton>
                                </div>
                            ) : (
                                <PluginDrawer />
                            )}
                            {!onboardingSidebarEnabled && <PanelSupport />}
                        </LemonModal>
                    )}
                </>
            )}
        </>
    )
}

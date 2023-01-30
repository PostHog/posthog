import { useValues, useActions } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ingestionLogic } from '../ingestionLogic'
import './Panels.scss'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { thirdPartySources, ThirdPartySourceType } from '../constants'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginInstallationType, PluginRepositoryEntryType, PluginTypeWithConfig } from 'scenes/plugins/types'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { PanelFooterToRecordingStep } from 'scenes/ingestion/v1/panels/PanelComponents'

export function ThirdPartyPanel(): JSX.Element {
    const { setInstructionsModal, setThirdPartySource, openThirdPartyPluginModal } = useActions(ingestionLogic)
    const { filteredUninstalledPlugins, installedPlugins } = useValues(pluginsLogic)
    const { installPlugin } = useActions(pluginsLogic)
    const {
        reportIngestionThirdPartyAboutClicked,
        reportIngestionThirdPartyConfigureClicked,
        reportIngestionThirdPartyPluginInstalled,
    } = useActions(eventUsageLogic)

    return (
        <div style={{ maxWidth: 800 }}>
            <div className="px-6">
                <h1 className="ingestion-title">Set up apps</h1>
                {thirdPartySources.map((source, idx) => {
                    const installedThirdPartyPlugin = installedPlugins?.find((plugin: PluginTypeWithConfig) =>
                        plugin.name.includes(source.name)
                    )
                    return (
                        <div
                            key={source.name}
                            className="p-4 mb-2"
                            style={{
                                border: '2px solid var(--border-light)',
                                borderRadius: 4,
                            }}
                        >
                            <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center">
                                    {source.icon}
                                    <div className="ml-2">
                                        <h3 className="mb-0 flex align-center font-semibold text-base">
                                            {source.name} Import
                                            {source.labels?.map((label, labelIdx) => (
                                                <LemonTag
                                                    key={labelIdx}
                                                    type={label === 'beta' ? 'warning' : 'default'}
                                                    className="uppercase ml-2"
                                                >
                                                    {label}
                                                </LemonTag>
                                            ))}
                                        </h3>
                                        <p className="mb-0 text-muted">Send events from {source.name} into PostHog</p>
                                    </div>
                                </div>
                                <div className="flex">
                                    <LemonButton
                                        className="mr-2"
                                        type="secondary"
                                        to={`https://posthog.com${
                                            source.type === ThirdPartySourceType.Integration
                                                ? `/docs/integrate/third-party/${source.name.toLowerCase()}`
                                                : `/integrations/${source.pluginName?.toLowerCase()}`
                                        }`}
                                        targetBlank={true}
                                        onClick={() => {
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
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
            <IntegrationInstructionsModal />
            <PanelFooterToRecordingStep />
        </div>
    )
}

export function IntegrationInstructionsModal(): JSX.Element {
    const { instructionsModalOpen, thirdPartyIntegrationSource, thirdPartyPluginSource } = useValues(ingestionLogic)
    const { setInstructionsModal } = useActions(ingestionLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            {thirdPartyPluginSource?.config_schema ? (
                <PluginDrawer />
            ) : (
                <>
                    {thirdPartyIntegrationSource?.name && (
                        <LemonModal
                            width={600}
                            isOpen={instructionsModalOpen}
                            onClose={() => setInstructionsModal(false)}
                            title="Configure integration"
                            footer={
                                <LemonButton
                                    fullWidth
                                    center
                                    type="primary"
                                    onClick={() => setInstructionsModal(false)}
                                >
                                    Done
                                </LemonButton>
                            }
                        >
                            {thirdPartyIntegrationSource.type === ThirdPartySourceType.Integration ? (
                                <div>
                                    <h1 className="ingestion-title">
                                        {thirdPartyIntegrationSource.icon}
                                        <span>Integrate with {thirdPartyIntegrationSource.name}</span>
                                    </h1>
                                    <div style={{ borderTop: '2px dashed var(--border)' }}>
                                        <div
                                            className="p-5 mt-6 mb-4 font-medium"
                                            style={{
                                                backgroundColor: 'var(--side)',
                                            }}
                                        >
                                            <p>
                                                The{' '}
                                                <a target="_blank" href={thirdPartyIntegrationSource.docsLink}>
                                                    {thirdPartyIntegrationSource.name} docs page for the PostHog
                                                    integration
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
                                        onClick={() => window.open(thirdPartyIntegrationSource.docsLink)}
                                        sideIcon={<IconOpenInNew style={{ color: 'var(--primary)' }} />}
                                    >
                                        Take me to the {thirdPartyIntegrationSource.name} docs
                                    </LemonButton>
                                    <div className="mb-6 mt-4">
                                        <h4>Steps:</h4>
                                        <ol className="pl-4">
                                            <li>
                                                Complete the steps for the {thirdPartyIntegrationSource.name}{' '}
                                                integration.
                                            </li>
                                            <li>
                                                Close this step and click <strong>continue</strong> to begin listening
                                                for events.
                                            </li>
                                        </ol>
                                    </div>
                                </div>
                            ) : (
                                <PluginDrawer />
                            )}
                        </LemonModal>
                    )}
                </>
            )}
        </>
    )
}

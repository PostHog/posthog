import { useValues, useActions } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CardContainer } from '../CardContainer'
import { ingestionLogic } from '../ingestionLogic'
import './Panels.scss'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { thirdPartySources } from '../constants'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Link } from '@posthog/lemon-ui'

export function ThirdPartyPanel(): JSX.Element {
    const { setInstructionsModal, setThirdPartySource } = useActions(ingestionLogic)
    const { reportIngestionThirdPartyAboutClicked, reportIngestionThirdPartyConfigureClicked } =
        useActions(eventUsageLogic)

    return (
        <CardContainer nextProps={{ readyToVerify: true }}>
            <div className="px-6">
                <h1 className="ingestion-title pb-4">Set up third-party integrations</h1>
                {thirdPartySources.map((source, idx) => {
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
                                    <div className="w-8 h-8">{source.icon}</div>
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
                                        <p className="mb-0 text-muted">
                                            {source.description
                                                ? source.description
                                                : `Send events from ${source.name} into PostHog`}
                                        </p>
                                    </div>
                                </div>
                                <div className="flex">
                                    <LemonButton
                                        className="mr-2"
                                        type="secondary"
                                        to={source.docsLink}
                                        targetBlank={true}
                                        onClick={() => {
                                            reportIngestionThirdPartyAboutClicked(source.name)
                                        }}
                                    >
                                        About
                                    </LemonButton>
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
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
            <IntegrationInstructionsModal />
        </CardContainer>
    )
}

export function IntegrationInstructionsModal(): JSX.Element {
    const { instructionsModalOpen, thirdPartyIntegrationSource } = useValues(ingestionLogic)
    const { setInstructionsModal } = useActions(ingestionLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            {thirdPartyIntegrationSource?.name && (
                <LemonModal
                    width={600}
                    isOpen={instructionsModalOpen}
                    onClose={() => setInstructionsModal(false)}
                    title="Configure integration"
                    footer={
                        <LemonButton fullWidth center type="primary" onClick={() => setInstructionsModal(false)}>
                            Done
                        </LemonButton>
                    }
                >
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
                                    <Link to={thirdPartyIntegrationSource.docsLink}>
                                        {thirdPartyIntegrationSource.name} docs page for the PostHog integration
                                    </Link>{' '}
                                    provides a detailed overview of how to set up this integration.
                                </p>
                                <b>PostHog Project API Key</b>
                                <CodeSnippet thing="project API key">{currentTeam?.api_token || ''}</CodeSnippet>
                            </div>
                        </div>
                        <LemonButton
                            type="secondary"
                            fullWidth
                            center
                            onClick={() => window.open(thirdPartyIntegrationSource.aboutLink)}
                            sideIcon={<IconOpenInNew style={{ color: 'var(--primary)' }} />}
                        >
                            Take me to the {thirdPartyIntegrationSource.name} docs
                        </LemonButton>
                        <div className="mb-6 mt-4">
                            <h4>Steps:</h4>
                            <ol className="pl-4">
                                <li>Complete the steps for the {thirdPartyIntegrationSource.name} integration.</li>
                                <li>
                                    Close this step and click <strong>continue</strong> to begin listening for events.
                                </li>
                            </ol>
                        </div>
                    </div>
                </LemonModal>
            )}
        </>
    )
}

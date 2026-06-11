import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonModal, LemonSkeleton } from '@posthog/lemon-ui'

import { AllowTrainingCallout } from 'lib/components/AllowTrainingCallout/AllowTrainingCallout'
import { useHogfetti } from 'lib/components/Hogfetti/Hogfetti'
import { IconSlack } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import SourceForm from 'products/data_warehouse/frontend/shared/components/forms/SourceForm'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { SessionAnalysisSetup } from '../../SessionAnalysisSetup'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { SourcesList } from '../../SourcesList'
import { AutoStartThresholdSection } from './AutoStartThresholdSection'
import { ConnectionsSection } from './ConnectionsSection'
import { McpServersSection } from './McpServersSection'

// Each signal source reads from specific tables — pre-select them and make them required
const SIGNAL_SOURCE_REQUIRED_TABLES: Partial<Record<ExternalDataSourceType, string[]>> = {
    Github: ['issues'],
    Linear: ['issues'],
    Zendesk: ['tickets'],
    PgAnalyze: ['issues', 'servers'],
}

function Section({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div>
                <h4 className="font-semibold text-sm mb-0">{title}</h4>
                {description && <p className="text-xs text-secondary mt-0.5 mb-0">{description}</p>}
            </div>
            {children}
        </div>
    )
}

/**
 * The "Configure agents" modal — supersedes the old SourcesModal. It groups the
 * source roster (reused from SourcesList) alongside connections, Slack, per-user
 * auto-start, and a link to MCP servers. Open/close state is shared with
 * `signalSourcesLogic` (sourcesModalOpen) so the toolbar button can keep using
 * `openSourcesModal`.
 */
export function ConfigureAgentsModal(): JSX.Element {
    const { sourcesModalOpen, sessionAnalysisSetupOpen, dataSourceSetupProduct } = useValues(signalSourcesLogic)
    const { closeSourcesModal, closeSessionAnalysisSetup, closeDataSourceSetup, onDataSourceSetupComplete } =
        useActions(signalSourcesLogic)
    const { trigger: triggerHogfetti, HogfettiComponent } = useHogfetti({ count: 30, duration: 3000 })

    const isDataSourceSetupOpen = dataSourceSetupProduct !== null
    const isSubFlowOpen = sessionAnalysisSetupOpen || isDataSourceSetupOpen

    const handleDataSourceComplete = (): void => {
        triggerHogfetti()
        setTimeout(() => triggerHogfetti(), 200)
        setTimeout(() => triggerHogfetti(), 400)
        onDataSourceSetupComplete(dataSourceSetupProduct!)
    }

    return (
        <>
            <LemonModal
                isOpen={sourcesModalOpen}
                onClose={closeSourcesModal}
                simple
                width={isSubFlowOpen ? '48rem' : '40rem'}
            >
                <LemonModal.Header>
                    <div className="flex items-center gap-2">
                        {isSubFlowOpen && (
                            <LemonButton
                                type="tertiary"
                                size="small"
                                icon={<IconArrowLeft />}
                                onClick={isDataSourceSetupOpen ? closeDataSourceSetup : closeSessionAnalysisSetup}
                            />
                        )}
                        <h3 className="font-semibold mb-0">
                            {isDataSourceSetupOpen
                                ? `Connect ${dataSourceSetupProduct}`
                                : sessionAnalysisSetupOpen
                                  ? 'Session analysis filters'
                                  : 'Configure agents'}
                        </h3>
                    </div>
                    {!isSubFlowOpen && (
                        <p className="text-xs text-secondary mt-1 mb-0">
                            Set up what your agents watch, where they post, and when they ship.
                        </p>
                    )}
                </LemonModal.Header>
                <LemonModal.Content className={sessionAnalysisSetupOpen ? 'p-0 rounded-b' : ''}>
                    {isDataSourceSetupOpen ? (
                        <DataSourceSetup product={dataSourceSetupProduct} onComplete={handleDataSourceComplete} />
                    ) : sessionAnalysisSetupOpen ? (
                        <SessionAnalysisSetup />
                    ) : (
                        <div className="flex flex-col gap-6">
                            <AllowTrainingCallout featureName="Inbox" />

                            <Section
                                title="Connections"
                                description="Foundational integrations agents read from and write to."
                            >
                                <ConnectionsSection />
                            </Section>

                            <LemonDivider className="my-0" />

                            <Section
                                title="Agents"
                                description="Each source watches for signals, spins up an agent when something matters, and hands you solutions."
                            >
                                <SourcesList />
                            </Section>

                            <LemonDivider className="my-0" />

                            <Section
                                title="Slack notifications"
                                description="Post reports to channels and ping suggested reviewers. Invite PostHog with /invite @PostHog in each channel you use."
                            >
                                <SlackNotificationsSection />
                            </Section>

                            <LemonDivider className="my-0" />

                            <Section
                                title="Auto-start"
                                description="Self-driving can start coding tasks automatically when a report is immediately actionable and assigned to you."
                            >
                                <AutoStartThresholdSection />
                            </Section>

                            <LemonDivider className="my-0" />

                            <Section
                                title="MCP servers"
                                description="External tools agents can read from. PostHog data is always available; this is everything else."
                            >
                                <McpServersSection />
                            </Section>
                        </div>
                    )}
                </LemonModal.Content>
            </LemonModal>
            {createPortal(
                <HogfettiComponent />,
                document.body /* Needs to be in portal to be above ReactModalPortal */
            )}
        </>
    )
}

function SlackNotificationsSection(): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-4 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start gap-3 min-w-0">
                <IconSlack className="size-5 shrink-0 mt-0.5 grayscale" />
                <div className="min-w-0">
                    <div className="font-medium text-sm">Slack delivery</div>
                    <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                        Connect Slack to post reports to channels and ping suggested reviewers.
                    </p>
                </div>
            </div>
            <LemonButton
                type="secondary"
                size="small"
                to={urls.settings('environment-integrations', 'integration-slack')}
                targetBlank
            >
                Manage
            </LemonButton>
        </div>
    )
}

function DataSourceSetup({
    product,
    onComplete,
}: {
    product: ExternalDataSourceType
    onComplete: () => void
}): JSX.Element {
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesLogic)

    if (availableSourcesLoading || availableSources === null) {
        return <LemonSkeleton />
    }

    const sourceConfig = Object.values(availableSources).find((s: SourceConfig) => s.name === product)
    if (!sourceConfig) {
        return <div>Source not found</div>
    }

    return (
        <BindLogic
            logic={sourceWizardLogic}
            props={{
                availableSources,
                requiredTables: SIGNAL_SOURCE_REQUIRED_TABLES[product],
                onComplete,
            }}
        >
            <DataSourceSetupForm sourceConfig={sourceConfig} />
        </BindLogic>
    )
}

function DataSourceSetupForm({ sourceConfig }: { sourceConfig: SourceConfig }): JSX.Element {
    const { isLoading, canGoNext } = useValues(sourceWizardLogic)
    const { setInitialConnector, onSubmit } = useActions(sourceWizardLogic)

    useEffect(() => {
        setInitialConnector(sourceConfig)
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-3">
                <SourceIcon type={sourceConfig.name} size="small" disableTooltip />
                <p className="text-sm text-muted-alt mb-0">
                    Connect {sourceConfig.label ?? sourceConfig.name} as a data source to enable this signal.
                </p>
            </div>

            <SourceForm sourceConfig={sourceConfig} showPrefix={false} />

            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    loading={isLoading}
                    disabledReason={!canGoNext ? 'Fill in the required fields' : undefined}
                    onClick={() => onSubmit()}
                >
                    Connect
                </LemonButton>
            </div>
        </div>
    )
}

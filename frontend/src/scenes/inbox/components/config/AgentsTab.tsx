import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ExternalDataSourceType, SourceConfig } from '~/queries/schema/schema-general'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { sourceWizardLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/sourceWizardLogic'
import SourceForm from 'products/data_warehouse/frontend/shared/components/forms/SourceForm'
import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { SessionAnalysisSetup } from '../../SessionAnalysisSetup'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { AgentsRoster } from './AgentsRoster'
import { ConnectionsSection } from './ConnectionsSection'
import { McpServersSection } from './McpServersSection'
import { ScoutsFleetSection } from './scouts/ScoutsFleetSection'
import { SlackNotificationsSection } from './SlackNotificationsSection'

// Each signal source reads from specific tables – pre-select them and make them required
const SIGNAL_SOURCE_REQUIRED_TABLES: Partial<Record<ExternalDataSourceType, string[]>> = {
    Github: ['issues'],
    Linear: ['issues'],
    Zendesk: ['tickets'],
    PgAnalyze: ['issues', 'servers'],
}

function Subsection({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-4 border-t border-primary pt-6 first:border-t-0 first:pt-0">
            <div className="flex flex-col gap-1">
                <h4 className="font-semibold text-sm text-default mb-0">{title}</h4>
                {description && (
                    <p className="text-xs text-secondary mt-0 mb-0 max-w-2xl leading-snug">{description}</p>
                )}
            </div>
            {children}
        </div>
    )
}

function BackLink({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={onClick} className="-ml-2 w-fit">
            Back
        </LemonButton>
    )
}

/**
 * Full-page Agents tab body for cloud Inbox – a high-fidelity port of the
 * PostHog Code desktop Agents view. Composes Connections, the agent roster,
 * Slack, and MCP servers. Session-analysis and data-source setup
 * render inline (replacing the roster) when their sub-flow is open.
 */
export function AgentsTab(): JSX.Element {
    const { sessionAnalysisSetupOpen, dataSourceSetupProduct } = useValues(signalSourcesLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        loadSources,
        loadSourceConfigs,
        closeSessionAnalysisSetup,
        closeDataSourceSetup,
        onDataSourceSetupComplete,
    } = useActions(signalSourcesLogic)

    useEffect(() => {
        loadSources()
        loadSourceConfigs()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    const isDataSourceSetupOpen = dataSourceSetupProduct !== null

    let agentsBody: JSX.Element
    if (isDataSourceSetupOpen) {
        agentsBody = (
            <div className="flex flex-col gap-3">
                <BackLink onClick={closeDataSourceSetup} />
                <DataSourceSetup
                    product={dataSourceSetupProduct}
                    onComplete={() => onDataSourceSetupComplete(dataSourceSetupProduct)}
                />
            </div>
        )
    } else if (sessionAnalysisSetupOpen) {
        agentsBody = (
            <div className="flex flex-col gap-3">
                <BackLink onClick={closeSessionAnalysisSetup} />
                <SessionAnalysisSetup />
            </div>
        )
    } else {
        agentsBody = <AgentsRoster />
    }

    return (
        <div className="flex flex-col">
            <div className="mx-auto max-w-4xl w-full px-6 py-6 flex flex-col gap-8">
                <Subsection
                    title="Connections"
                    description="Foundational integrations responders read from and write to."
                >
                    <ConnectionsSection />
                </Subsection>

                <Subsection
                    title="Scouts"
                    description="Scheduled agents that sweep this project on a cadence and emit findings to your inbox."
                >
                    <ScoutsFleetSection />
                </Subsection>

                <Subsection
                    title="Responders"
                    description="Each source: 1. watches for signals, 2. spins up a Responder when something matters, 3. hands you solutions."
                >
                    {agentsBody}
                </Subsection>

                {featureFlags[FEATURE_FLAGS.INBOX_SLACK_NOTIFICATIONS] && (
                    <Subsection
                        title="Slack"
                        description="Post reports to channels and ping suggested reviewers. Invite PostHog with /invite @PostHog in each channel you use."
                    >
                        <SlackNotificationsSection />
                    </Subsection>
                )}

                {featureFlags[FEATURE_FLAGS.MCP_SERVERS] && (
                    <Subsection
                        title="MCP servers"
                        description="External tools agents can read from. PostHog data is always available; this is everything else."
                    >
                        <McpServersSection />
                    </Subsection>
                )}
            </div>
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

export default AgentsTab

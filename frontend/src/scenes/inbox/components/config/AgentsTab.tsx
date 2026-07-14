import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SessionAnalysisSetup } from '../../SessionAnalysisSetup'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { AgentsRoster } from './AgentsRoster'
import { ConnectionsSection } from './ConnectionsSection'
import { DataSourceSetup } from './DataSourceSetup'
import { McpServersSection } from './McpServersSection'
import { ScoutsFleetSection } from './scouts/ScoutsFleetSection'
import { SlackNotificationsSection } from './SlackNotificationsSection'

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
    const { sessionAnalysisSetupOpen, dataSourceSetupSource } = useValues(signalSourcesLogic)
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

    const isDataSourceSetupOpen = dataSourceSetupSource !== null

    let agentsBody: JSX.Element
    if (isDataSourceSetupOpen) {
        agentsBody = (
            <div className="flex flex-col gap-3">
                <BackLink onClick={closeDataSourceSetup} />
                <DataSourceSetup source={dataSourceSetupSource} onComplete={() => onDataSourceSetupComplete()} />
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

export default AgentsTab

import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconTerminal } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { MCP_INSTALL_COMMAND } from 'lib/components/MCPHint/constants'
import { mcpHintLogic } from 'lib/components/MCPHint/mcpHintLogic'
import { getSurfacePrompts, stripDisplayQuotes } from 'lib/components/MCPHint/prompts'
import { preflightLogic } from 'lib/logic/preflightLogic'

const SURFACE_KEY = 'ai_observability_evaluations.create'

export function EvaluationAgentActions(): JSX.Element | null {
    const { effectiveOptOut, userRole } = useValues(mcpHintLogic)
    const { reportUseCaseCardShown, reportAgentOpened } = useActions(mcpHintLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    // The PostHog MCP server only serves cloud and dev instances. Unknown while preflight loads, so only a known self-hosted instance hides the actions.
    const visible = !effectiveOptOut && isCloudOrDev !== false

    useEffect(() => {
        if (visible) {
            reportUseCaseCardShown(SURFACE_KEY)
        }
    }, [visible, reportUseCaseCardShown])

    if (!visible) {
        return null
    }

    const prompt = stripDisplayQuotes(getSurfacePrompts(SURFACE_KEY, { role: userRole, topEvents: [] }).examples[0])

    return (
        <>
            <LemonDropdown
                overlay={
                    <div className="flex flex-col gap-2 p-1 max-w-[24rem]">
                        <span className="text-xs text-secondary">
                            Run this once so your agent can read your traces through the PostHog MCP server.
                        </span>
                        <CommandBlock
                            command={MCP_INSTALL_COMMAND}
                            copyLabel="MCP install command"
                            ariaLabel="Copy MCP install command"
                            size="sm"
                            decoration="rainbow"
                            className="bg-surface-secondary border border-primary !m-0 hover:border-accent"
                        />
                    </div>
                }
                placement="bottom-start"
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconTerminal />}
                    data-attr="evaluation-agent-mcp-setup"
                >
                    Connect MCP
                </LemonButton>
            </LemonDropdown>
            <AgentPromptButton
                actions={[{ key: 'prompt', label: 'prompt', buildPrompt: () => prompt }]}
                labelMode="destination"
                appearance="lemon"
                onRun={({ agentKey }) => reportAgentOpened(SURFACE_KEY, 'card', agentKey)}
                data-attr="mcp-hint-card-agent-button"
            />
        </>
    )
}

import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconSparkles } from '@posthog/icons'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
import { CodeSnippet } from 'lib/components/CodeSnippet/CodeSnippet'
import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { MCP_INSTALL_COMMAND } from 'lib/components/MCPHint/constants'
import { mcpHintLogic } from 'lib/components/MCPHint/mcpHintLogic'
import { getSurfacePrompts, stripDisplayQuotes } from 'lib/components/MCPHint/prompts'
import { preflightLogic } from 'lib/logic/preflightLogic'

const SURFACE_KEY = 'ai_observability_evaluations.create'

export function EvaluationAgentCard(): JSX.Element | null {
    const { effectiveOptOut, userRole } = useValues(mcpHintLogic)
    const { reportUseCaseCardShown, reportAgentOpened } = useActions(mcpHintLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const visible = !effectiveOptOut

    useEffect(() => {
        if (visible) {
            reportUseCaseCardShown(SURFACE_KEY)
        }
    }, [visible, reportUseCaseCardShown])

    if (!visible) {
        return null
    }

    const [prompt] = getSurfacePrompts(SURFACE_KEY, { role: userRole, topEvents: [] }).examples

    return (
        <div className="flex flex-col gap-2 p-3 rounded-lg border border-primary bg-surface-primary">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="flex items-center gap-2 m-0 text-sm font-semibold">
                    <IconSparkles className="size-4 shrink-0 text-accent" />
                    <span>Find evaluations with your agent</span>
                </h2>
                {/* The PostHog MCP server only serves cloud and dev instances, so a self-hosted user has nothing to connect to. */}
                {isCloudOrDev && (
                    <AgentPromptButton
                        actions={[
                            {
                                key: 'prompt',
                                label: 'prompt',
                                buildPrompt: () => stripDisplayQuotes(prompt),
                            },
                        ]}
                        labelMode="destination"
                        size="sm"
                        variant="outline"
                        onRun={({ agentKey }) => reportAgentOpened(SURFACE_KEY, 'card', agentKey)}
                        data-attr="mcp-hint-card-agent-button"
                    />
                )}
            </div>
            <CodeSnippet compact wrap thing="prompt" className="w-full">
                {prompt}
            </CodeSnippet>
            {isCloudOrDev && (
                <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
                    <span>First time? Connect the PostHog MCP server:</span>
                    <CommandBlock
                        command={MCP_INSTALL_COMMAND}
                        copyLabel="MCP install command"
                        ariaLabel="Copy MCP install command"
                        size="sm"
                        className="bg-surface-secondary border border-primary !m-0"
                    />
                </div>
            )}
        </div>
    )
}

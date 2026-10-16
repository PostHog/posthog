import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCopy, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { MCP_INSTALL_COMMAND } from 'lib/components/MCPHint/constants'
import { mcpHintLogic } from 'lib/components/MCPHint/mcpHintLogic'
import { getSurfacePrompts, stripDisplayQuotes } from 'lib/components/MCPHint/prompts'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

const SURFACE_KEY = 'ai_observability_evaluations.create'

export function EvaluationAgentCard(): JSX.Element | null {
    const { effectiveOptOut, userRole } = useValues(mcpHintLogic)
    const { reportUseCaseCardShown, reportAgentOpened } = useActions(mcpHintLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    // The PostHog MCP server only serves cloud and dev instances. Unknown while preflight loads, so only a known self-hosted instance hides the card.
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
        <div className="flex gap-3 p-3 rounded-lg border border-primary bg-surface-primary">
            <div className="flex items-center justify-center size-10 shrink-0 rounded-lg bg-fill-secondary text-accent">
                <IconSparkles className="size-5" />
            </div>
            <div className="flex flex-col flex-1 min-w-0 gap-2">
                <div>
                    <h2 className="m-0 text-sm font-semibold">Let your agent find them</h2>
                    <p className="m-0 text-xs text-secondary">
                        It reads your recent traces and suggests evaluations for the problems it finds.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-secondary">
                    <span>First time? Connect the PostHog MCP server:</span>
                    <CommandBlock
                        command={MCP_INSTALL_COMMAND}
                        copyLabel="MCP install command"
                        ariaLabel="Copy MCP install command"
                        size="sm"
                        decoration="rainbow"
                        className="bg-surface-secondary border border-primary !m-0 hover:border-accent"
                    />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <AgentPromptButton
                        actions={[{ key: 'prompt', label: 'prompt', buildPrompt: () => prompt }]}
                        labelMode="destination"
                        size="sm"
                        variant="outline"
                        onRun={({ agentKey }) => reportAgentOpened(SURFACE_KEY, 'card', agentKey)}
                        data-attr="mcp-hint-card-agent-button"
                    />
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconCopy />}
                        onClick={() => {
                            void copyToClipboard(prompt, 'prompt')
                            reportAgentOpened(SURFACE_KEY, 'card', 'clipboard')
                        }}
                        data-attr="evaluation-agent-card-copy-prompt"
                    >
                        Copy prompt
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

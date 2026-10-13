import { useActions, useValues } from 'kea'

import { AgentPromptButton, type AgentPromptDestination } from 'lib/components/AgentPromptButton'
import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { projectLogic } from 'scenes/projectLogic'

import { MCP_INSTALL_COMMAND } from './constants'
import { type MCPHintPlacement, mcpHintLogic } from './mcpHintLogic'
import { buildMCPAgentPrompt, type SurfaceKey } from './prompts'

// PostHog AI already runs inside the app, and a cloud session on claude.ai cannot reach a locally configured MCP server.
const MCP_AGENT_KEYS: AgentPromptDestination[] = [
    'claude-code',
    'claude-desktop',
    'claude-code-vscode',
    'cursor',
    'codex',
    'posthog-code',
    'clipboard',
]

export function MCPHintActions({
    surfaceKey,
    example,
    placement,
    onMenuOpen,
}: {
    surfaceKey: SurfaceKey
    /** The example prompt shown on the surface. The agent receives it with MCP setup instructions. */
    example: string
    placement: MCPHintPlacement
    onMenuOpen?: () => void
}): JSX.Element | null {
    const { isCloudOrDev } = useValues(preflightLogic)
    const { currentProjectId } = useValues(projectLogic)
    const { reportAgentOpened } = useActions(mcpHintLogic)

    // The PostHog MCP server only serves cloud and dev instances, so a self-hosted user has nothing to connect to.
    if (!isCloudOrDev) {
        return null
    }

    return (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <CommandBlock
                command={MCP_INSTALL_COMMAND}
                copyLabel="MCP install command"
                ariaLabel="Copy MCP install command"
                size="sm"
                decoration="rainbow"
                // The toast is itself a notification, so a second "Copied" toast would stack on top of it.
                silentCopy={placement === 'toast'}
                className="bg-surface-secondary border border-primary !m-0 hover:border-accent"
            />
            <div className="flex items-center gap-2">
                <span className="text-xs text-muted">or</span>
                <AgentPromptButton
                    storageKey="mcp-hint"
                    actions={[
                        {
                            key: 'prompt',
                            label: 'prompt',
                            buildPrompt: () => buildMCPAgentPrompt(example, currentProjectId),
                        },
                    ]}
                    agentKeys={MCP_AGENT_KEYS}
                    defaultAgentKey="claude-code"
                    agentSelectionMode="run"
                    labelMode="destination"
                    size="sm"
                    variant="outline"
                    onRun={({ agentKey }) => reportAgentOpened(surfaceKey, placement, agentKey)}
                    onOpenChange={(open) => open && onMenuOpen?.()}
                    // Radix menus sit below react-toastify's container, so a menu opened from the toast would render behind it.
                    menuClassName={placement === 'toast' ? 'z-[calc(var(--toastify-z-index)+1)]' : undefined}
                    data-attr={`mcp-hint-${placement}-agent-button`}
                />
            </div>
        </div>
    )
}

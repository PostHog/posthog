import { detectedMcpAgent, hasMcpServer, MCP_CLIENTS, whereFor } from '@/commands/mcp/clients'
import { findGitRoot } from '@/core/paths'

import type { McpContext } from '../result'
import { completed, type SetupRun, type Step } from '../setup-run'

async function mcpContext(run: SetupRun): Promise<McpContext> {
    const { runtime, mode } = run.ctx
    const agent = detectedMcpAgent(mode.agent, runtime.env)
    if (agent === undefined) {
        return { agent: null, configured: false, command: 'hog mcp add --agent <name>' }
    }

    const root = (await findGitRoot(runtime))?.root ?? runtime.cwd()
    const configured = await hasMcpServer(agent, whereFor(runtime, root)).catch(() => false)
    return { agent, configured, command: `hog mcp add --agent ${agent}` }
}

// Only reads, so it never stops and records nothing. It counts as done once the setup is, so a connected
// folder's summary lists it.
export const mcp: Step = {
    isDone: (run) => Promise.resolve(completed(run, 'connected')),

    summary: (run) => {
        const found = run.context.mcp
        return found?.agent && found.configured
            ? `${MCP_CLIENTS[found.agent].name} has the PostHog MCP server`
            : 'Checked for the PostHog MCP server'
    },

    async advance(run) {
        run.context.mcp = await mcpContext(run)
        return undefined
    },
}

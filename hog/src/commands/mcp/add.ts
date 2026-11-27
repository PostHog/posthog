import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { findGitRoot } from '@/core/paths'
import type { Env } from '@/core/runtime'
import { parseOrThrow } from '@/core/schema'

import {
    addServer,
    detectedMcpAgent,
    MCP_AGENTS,
    MCP_CLIENTS,
    McpAgentName,
    mcpUrl,
    planAdd,
    whereFor,
    type AddedServer,
    type McpAgent,
} from './clients'

const AGENT_HINT = `Pass \`--agent\` with one of: ${MCP_AGENTS.join(', ')}.`

interface AddResult {
    agentSource: 'option' | 'detected'
    added: AddedServer[]
}

function chosenAgents(
    chosen: readonly string[] | undefined,
    detected: string | undefined,
    env: Env
): { source: AddResult['agentSource']; agents: McpAgent[] } {
    if (chosen?.length) {
        const failure = { code: 'unknown_agent', hint: AGENT_HINT, exitCode: EXIT_USAGE }
        return {
            source: 'option',
            agents: [...new Set(chosen.map((name) => parseOrThrow(McpAgentName, name, failure)))],
        }
    }

    const agent = detectedMcpAgent(detected, env)
    if (agent === undefined) {
        throw new HogError(
            'mcp_agent_required',
            detected === undefined
                ? "No agent is running hog, so hog doesn't know which agent to add the MCP server to."
                : `hog can't add the MCP server to ${escapeControls(detected)}.`,
            AGENT_HINT,
            EXIT_USAGE
        )
    }

    return { source: 'detected', agents: [agent] }
}

export default defineCommand({
    description: "Connect PostHog's MCP server to your agent",
    options: {
        agent: {
            type: 'string',
            multiple: true,
            placeholder: 'name',
            description: `The agent to add the server to, instead of the one running hog. Repeat it to add several. One of: ${MCP_AGENTS.join(', ')}`,
        },
        force: { type: 'boolean', description: 'Write the PostHog entry again when the agent already has one' },
    },
    writes: true,
    notes: [
        'The server URL has no key in it. Each agent logs in to PostHog with OAuth the first time it connects.',
        'Claude Code gets `.mcp.json` in the closest git repository, or in the current folder outside one. Other agents get their user settings file.',
        'Other servers in the file stay as they are.',
    ].join('\n'),
    examples: ['hog mcp add', 'hog mcp add --agent cursor --agent vscode'],

    async run({ options, ctx }): Promise<AddResult> {
        const { source, agents } = chosenAgents(options.agent, ctx.mode.agent, ctx.runtime.env)

        const repository = await findGitRoot(ctx.runtime)
        const where = whereFor(ctx.runtime, repository?.root ?? ctx.runtime.cwd())
        const [url, plans] = await Promise.all([mcpUrl(ctx), planAdd(agents, where)])

        const added: AddedServer[] = []
        for (const plan of plans) {
            added.push(await addServer(plan, where, url, options.force === true))
        }

        return { agentSource: source, added }
    },

    human({ result, out }) {
        const changed = result.added.filter((server) => server.status !== 'already_added')
        const kept = result.added.filter((server) => server.status === 'already_added')
        const name = (server: AddedServer): string => MCP_CLIENTS[server.agent].name
        const names = (servers: readonly AddedServer[]): string =>
            new Intl.ListFormat('en', { type: 'conjunction' }).format(servers.map(name))
        // With several agents, each line names the agent it is about.
        const about = (server: AddedServer): string => (result.added.length > 1 ? `${name(server)}: ` : '')
        const keptLines = kept.map(
            (server) => `${name(server)} already has the PostHog MCP server in ${escapeControls(server.path)}.`
        )
        const force = kept.length > 0 ? ['Pass --force to write it again.'] : []

        if (changed.length === 0) {
            const [only] = kept
            out.report({
                status: 'unchanged',
                result:
                    only && kept.length === 1
                        ? `${name(only)} already has the PostHog MCP server in ${escapeControls(only.path)}`
                        : `${names(kept)} already have the PostHog MCP server`,
                notes: [...(kept.length > 1 ? keptLines : []), ...force],
            })
            return
        }

        out.report({
            result: `Added the PostHog MCP server to ${names(changed)}`,
            effects: changed.map(
                (server) =>
                    `${about(server)}${server.status === 'replaced' ? 'Replaced the old PostHog entry in' : 'Saved in'} ${escapeControls(server.path)}`
            ),
            notes: [...changed.map((server) => MCP_CLIENTS[server.agent].afterAdd), ...keptLines, ...force],
        })
    },

    agent({ result, out }) {
        out.json({ added: result.added })
    },

    telemetry: ({ result }) => ({
        mcp_agents: result.added.map((server) => server.agent).sort(),
        agent_source: result.agentSource,
        already_added: result.added.filter((server) => server.status === 'already_added').length,
    }),
})

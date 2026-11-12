import { isRunningInCI } from './ci'
import type { Env } from './runtime'

export const KNOWN_AGENTS = [
    'claude-code',
    'codex',
    'cursor',
    'gemini-cli',
    'cline',
    'opencode',
    'augment',
    'antigravity',
    'github-copilot',
] as const

export type KnownAgent = (typeof KNOWN_AGENTS)[number]

// Env vars that coding agents set for the commands they run, checked in order.
// Sources: the env vars @vercel/detect-agent and the Gauge CLI check. CURSOR_TRACE_ID and
// REPL_ID are left out on purpose, because people also see them in Cursor's and Replit's
// own terminals.
const AGENT_ENV_MARKERS: ReadonlyArray<readonly [envVar: string, agent: KnownAgent]> = [
    ['CLAUDECODE', 'claude-code'],
    ['CLAUDE_CODE', 'claude-code'],
    ['CODEX_SANDBOX', 'codex'],
    ['CODEX_CI', 'codex'],
    ['CODEX_THREAD_ID', 'codex'],
    ['CURSOR_AGENT', 'cursor'],
    ['GEMINI_CLI', 'gemini-cli'],
    ['CLINE_ACTIVE', 'cline'],
    ['OPENCODE', 'opencode'],
    ['OPENCODE_CLIENT', 'opencode'],
    ['AUGMENT_AGENT', 'augment'],
    ['ANTIGRAVITY_AGENT', 'antigravity'],
    ['COPILOT_MODEL', 'github-copilot'],
    ['COPILOT_ALLOW_ALL', 'github-copilot'],
]

const TRUE_VALUES = new Set(['1', 'true', 'yes'])
const FALSE_VALUES = new Set(['0', 'false', 'no'])

export type OutputFormat = 'text' | 'json'

// Who is calling hog, and how hog prints for them.
export interface Mode {
    // The agent running hog, or undefined for a person or a script.
    agent: string | undefined
    // Why hog decided the caller is or isn't an agent. `hog commands` reports it.
    agentReason: string
    format: OutputFormat
    color: boolean
    columns: number | undefined
    isCI: boolean
}

export interface Terminal {
    isTTY: boolean
    hasColors: boolean
    columns: number | undefined
}

function detectAgent(env: Env): { agent: string | undefined; reason: string } {
    const override = env.HOG_AGENT?.trim().toLowerCase()
    if (override !== undefined && FALSE_VALUES.has(override)) {
        return { agent: undefined, reason: 'HOG_AGENT disables agent detection' }
    }
    if (override !== undefined && TRUE_VALUES.has(override)) {
        return { agent: 'unknown', reason: 'HOG_AGENT forces agent mode' }
    }

    // AI_AGENT is the generic convention: its value names the agent.
    const generic = env.AI_AGENT?.trim()
    if (generic) {
        return { agent: generic, reason: 'AI_AGENT is set' }
    }

    for (const [envVar, agent] of AGENT_ENV_MARKERS) {
        if (env[envVar]) {
            return { agent, reason: `${envVar} is set` }
        }
    }
    return { agent: undefined, reason: 'no agent env var is set' }
}

// The agent hog knows behind a detected name. AI_AGENT can name an agent its own way, as Claude Code's
// `claude-code_<version>_agent` does, so the agent's own env var decides then.
export function knownAgent(agent: string, env: Env): KnownAgent | undefined {
    const named = KNOWN_AGENTS.find((known) => known === agent)
    if (named) {
        return named
    }

    return AGENT_ENV_MARKERS.find(([envVar]) => env[envVar])?.[1]
}

export function resolveMode(env: Env, terminal: Terminal, requestedFormat: OutputFormat | undefined): Mode {
    const { agent, reason } = detectAgent(env)
    // Agents and pipes get JSON by default, people at a terminal get text.
    const format = requestedFormat ?? (agent !== undefined || !terminal.isTTY ? 'json' : 'text')
    const colorForced = env.FORCE_COLOR !== undefined && env.FORCE_COLOR !== '0'
    const color =
        colorForced || (format === 'text' && terminal.hasColors && agent === undefined && env.NO_COLOR === undefined)
    return {
        agent,
        agentReason: reason,
        format,
        color,
        columns: terminal.columns,
        isCI: isRunningInCI(env),
    }
}

import type { McpAgent } from '@/commands/mcp/clients'
import type { RegionId } from '@/posthog/host'
import type { ProjectToken } from '@/posthog/tokens'

import type { WrittenFile } from './agents-md'
import type { Product, ProductId } from './products'
import type { StepId } from './state'

// The options of `hog setup`. Each one is an answer, so it counts as soon as it is given.
export interface SetupInput {
    next: boolean
    reason?: string
    products?: ProductId[]
    region?: RegionId
    reviewed?: boolean
}

// What has to happen before `hog setup next` can go on. Every instruction is for the agent, and says
// what it asks or tells the person and which command it runs itself.
export type NextAction =
    | { kind: 'run'; command: string; instructions: string }
    // A question for the person. The agent turns the answer into the options of `command`.
    | { kind: 'ask_user'; ask: string; command: string; instructions: string }
    | { kind: 'read'; read: string[]; command: string; instructions: string }
    | { kind: 'wait'; command: string; url: string; code: string | null; expiresAt: string; instructions: string }
    | { kind: 'done'; instructions: string }

export interface DoneStep {
    step: StepId
    summary: string
}

export interface EventsContext {
    since: string
    // Null when hog didn't count, as `hog setup` doesn't at the verify step.
    count: number | null
    query: string
}

export interface SkillInfo {
    id: string
    name: string
    description: string
}

// Whether the agent running setup has PostHog's MCP server. `agent` is null when no agent hog can add
// the server to is running it, and `command` then leaves the agent for the person to name.
export interface McpContext {
    agent: McpAgent | null
    configured: boolean
    command: string
    foreign: { path: string } | null
}

export interface SetupContext {
    folder: string
    configPath: string | null
    host: string | null
    projectId: string | null
    loggedIn: boolean
    token?: ProjectToken
    apiHost?: string
    agentsMd?: WrittenFile[]
    events?: EventsContext
    products?: (Product & { chosen: boolean })[]
    // PostHog skills that could help in later sessions, at the products step. Agents get the names only.
    skills?: SkillInfo[]
    mcp?: McpContext
    warnings: string[]
}

export interface SetupResult {
    step: StepId
    status: 'in_progress' | 'connected'
    // Why `hog setup next` stopped, for scripts. Null once connected.
    code: string | null
    done: DoneStep[]
    next: NextAction
    context: SetupContext
}

export interface Stop {
    code: string
    next: NextAction
}

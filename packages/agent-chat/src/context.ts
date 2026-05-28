/**
 * The chat dock is **ambient** — it's pinned to the app shell on every
 * route, and what it shows / how it talks depends on the current context.
 *
 * Two modes:
 *
 *   - **Concierge** — the default. A management AI that helps you
 *     inspect and edit your agents. The page you're on changes the
 *     starter prompts and the indicator, but the underlying agent is
 *     always the same (PostHog's concierge).
 *
 *   - **Playground** — explicit, entered from an agent's detail page.
 *     The chat is now *with the agent itself*, as a user would talk to
 *     it. Sticky across navigation — exits only via an explicit
 *     control in the dock.
 */

import type { AgentApplicationRef } from './types'

export type ConciergePageContext =
    | { kind: 'agent-list' }
    | { kind: 'agent'; agent: AgentApplicationRef }
    | { kind: 'agent-bundle'; agent: AgentApplicationRef; revisionLabel?: string }
    | { kind: 'agent-revisions'; agent: AgentApplicationRef }
    | { kind: 'agent-sessions'; agent: AgentApplicationRef }
    | { kind: 'agent-session'; agent: AgentApplicationRef; sessionId: string }
    | { kind: 'unknown' }

export type ChatContext =
    | { mode: 'concierge'; page: ConciergePageContext }
    | { mode: 'playground'; agent: AgentApplicationRef }

export interface StarterPrompt {
    id: string
    label: string
    prompt: string
}

/**
 * Default starter prompts per context. Consumers can override per-page
 * via the `starterPrompts` prop on `<AgentChat />` — these are the
 * sensible defaults.
 */
export function getStarterPrompts(context: ChatContext): StarterPrompt[] {
    if (context.mode === 'playground') {
        return [
            { id: 'p-1', label: 'Say hi', prompt: 'Hey! Walk me through what you can do.' },
            {
                id: 'p-2',
                label: 'Show a real example',
                prompt: 'Run a representative example end-to-end so I can see what your output looks like.',
            },
            { id: 'p-3', label: 'Edge cases', prompt: 'What inputs do you handle badly? Walk me through one.' },
        ]
    }

    switch (context.page.kind) {
        case 'agent-list':
            return [
                { id: 'l-1', label: 'What changed this week?', prompt: 'Summarize what changed across all my agents this week.' },
                { id: 'l-2', label: 'Anything erroring?', prompt: 'Which of my agents have errored in the last 24 hours?' },
                { id: 'l-3', label: 'Create a new agent', prompt: "I want to create a new agent. Walk me through what it should do." },
            ]
        case 'agent':
            return [
                {
                    id: 'a-1',
                    label: 'Explain this agent',
                    prompt: `Give me a quick rundown of what ${context.page.agent.name} does and how it's wired up.`,
                },
                { id: 'a-2', label: 'Recent sessions', prompt: `Show me ${context.page.agent.name}'s recent sessions and call out anything unusual.` },
                {
                    id: 'a-3',
                    label: 'Tighten the prompt',
                    prompt: 'Tighten the prompt — add a callout to mention Friday deploys in the sources list.',
                },
                { id: 'a-4', label: 'Make a change', prompt: `I want to change something about ${context.page.agent.name}. Help me plan it.` },
            ]
        case 'agent-bundle':
            return [
                { id: 'b-1', label: 'Explain this skill', prompt: 'Walk me through the skill that\'s open and what it does.' },
                { id: 'b-2', label: 'Add a new skill', prompt: 'I want to add a new skill to this bundle. Help me draft it.' },
                { id: 'b-3', label: 'Simplify', prompt: 'Where could this bundle be simpler without losing capability?' },
            ]
        case 'agent-revisions':
            return [
                { id: 'r-1', label: 'Compare last two', prompt: 'What changed between the live revision and the most recent draft?' },
                { id: 'r-2', label: 'Promote a draft', prompt: 'Walk me through promoting the latest draft.' },
            ]
        case 'agent-sessions':
            return [
                { id: 's-1', label: 'Anything off?', prompt: 'Surface any sessions from the last day that look anomalous.' },
                { id: 's-2', label: 'Cost summary', prompt: 'How much has this agent cost to run this week?' },
            ]
        case 'agent-session':
            return [
                { id: 'ses-1', label: 'Why this outcome?', prompt: 'Why did this session end the way it did?' },
                { id: 'ses-2', label: 'Replay with a tweak', prompt: 'I want to replay this with a different system prompt — help me set that up.' },
            ]
        case 'unknown':
        default:
            return [
                { id: 'u-1', label: 'What can you do?', prompt: 'What kinds of things can you help me do here?' },
                { id: 'u-2', label: 'Take me somewhere', prompt: 'Show me the agents I have set up.' },
            ]
    }
}

/**
 * Human-readable mode label rendered in the dock header.
 */
export function describeContext(context: ChatContext): { mode: string; subject: string } {
    if (context.mode === 'playground') {
        return { mode: 'Playground', subject: context.agent.name }
    }
    switch (context.page.kind) {
        case 'agent-list':
            return { mode: 'Concierge', subject: 'Your agents' }
        case 'agent':
        case 'agent-bundle':
        case 'agent-revisions':
        case 'agent-sessions':
            return { mode: 'Concierge', subject: context.page.agent.name }
        case 'agent-session':
            return { mode: 'Concierge', subject: `${context.page.agent.name} · session` }
        case 'unknown':
        default:
            return { mode: 'Concierge', subject: 'Anywhere' }
    }
}

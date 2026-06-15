/**
 * Build the system prompt from the revision bundle. Four layers:
 *
 *   1. Framework preamble — platform-owned guidance about the state
 *      machine, meta tools, and (slice 2+) tool failure / approval
 *      handling / reasoning hints. See `framework-preamble.ts`.
 *   2. agent.md (or spec.entrypoint) — author-owned instructions. Wins
 *      over the preamble through normal natural-language precedence
 *      (the model reads it after).
 *   3. Skills index — listed as one line per skill (`- <id>: <description>`).
 *      The model calls `@posthog/load-skill` (auto-included by the
 *      runner when spec.skills is non-empty) to fetch a body on
 *      demand. Keeps per-turn token usage low for agents with many
 *      skills.
 *   4. Unavailable capabilities — MCP ids the worker couldn't open this
 *      session (transport down, auth missing, etc.). Lets the agent
 *      know its tool set is degraded and tell the user without
 *      surfacing internal error strings.
 */

import { BundleStore } from '../storage/bundle'
import { renderFrameworkPreamble } from './framework-preamble'
import { AgentRevision } from './spec'

/** Coarse failure category — same shape the runner uses; redeclared here
 *  to avoid the runner→shared import cycle. Keep in sync with
 *  `agent-runner/src/loop/mcp-clients.ts#McpFailureCategory`. */
export type UnavailableMcpCategory = 'auth' | 'network' | 'not_found' | 'unknown'

export interface UnavailableMcp {
    /** Spec ref id — same string the model sees as the tool-name prefix. */
    id: string
    category: UnavailableMcpCategory
}

export interface BuildSystemPromptOpts {
    /**
     * MCP refs that failed to open for this session. Rendered as a brief
     * "unavailable capabilities" section so the model can shape its reply
     * (e.g. "I can't reach PostHog right now — let me try the rest").
     * Raw transport error strings are intentionally NOT included; they
     * live in `log_entries` for the agent owner.
     */
    unavailableMcps?: readonly UnavailableMcp[]
}

const CATEGORY_HINTS: Record<UnavailableMcpCategory, string> = {
    auth: 'authentication issue',
    network: 'network or upstream issue',
    not_found: 'endpoint not found',
    unknown: 'unavailable',
}

export async function buildSystemPrompt(
    rev: AgentRevision,
    bundle: BundleStore,
    opts: BuildSystemPromptOpts = {}
): Promise<string> {
    const parts: string[] = []

    // Framework preamble first — the author's agent.md can override its
    // defaults via normal natural-language instructions.
    parts.push(renderFrameworkPreamble(rev))

    const entry = rev.spec.entrypoint || 'agent.md'
    if (await bundle.exists(rev.id, entry)) {
        parts.push(await bundle.readText(rev.id, entry))
    } else {
        parts.push('(missing entrypoint — please add agent.md)')
    }

    if (rev.spec.skills.length > 0) {
        const lines = ['\n\n---\n\n## Available skills', '']
        lines.push('Call `@posthog/load-skill` with one of these ids to fetch the full body when you need it:')
        lines.push('')
        for (const skill of rev.spec.skills) {
            const desc = skill.description?.trim() || '(no description)'
            lines.push(`- \`${skill.id}\`: ${desc}`)
        }
        parts.push(lines.join('\n'))
    }

    const unavailable = opts.unavailableMcps ?? []
    if (unavailable.length > 0) {
        const lines = ['\n\n---\n\n## Unavailable capabilities', '']
        lines.push(
            'The following MCP servers your spec references failed to open for this session, so their tools are not callable:'
        )
        lines.push('')
        for (const u of unavailable) {
            lines.push(`- \`${u.id}\` — ${CATEGORY_HINTS[u.category]}`)
        }
        lines.push('')
        lines.push(
            'Continue helping the user with the tools you DO have. If they ask for something only an unavailable server can do, tell them the relevant capability is temporarily unavailable and let them know the agent owner can check the session logs for detail — do NOT paste raw error messages, transport URLs, or stack traces into the conversation.'
        )
        parts.push(lines.join('\n'))
    }

    return parts.join('\n')
}

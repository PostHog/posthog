/**
 * Build the system prompt from the revision bundle. Four layers:
 *
 *   1. Framework preamble — platform-owned guidance about the state
 *      machine, meta tools, and (slice 2+) tool failure / approval
 *      handling / reasoning hints. See `framework-preamble.ts`.
 *   2. agent.md — author-owned instructions. Wins
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
export type UnavailableMcpCategory = 'connection_dead' | 'auth' | 'network' | 'not_found' | 'unknown'

export interface UnavailableMcp {
    /** Spec ref id — same string the model sees as the tool-name prefix. */
    id: string
    category: UnavailableMcpCategory
    /** Set when the MCP didn't open because the asker hasn't linked its
     *  identity provider yet. The model relays this connect link rather than
     *  reporting a dead "temporarily unavailable". */
    authorizeUrl?: string
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
    /**
     * Set for slack-triggered sessions: the runner relays each finalized
     * assistant message into the thread automatically, so the model is told to
     * just reply normally and reserve `@posthog/slack-post-message` for advanced
     * sends. Without this note the chat-tuned model crams answers into tool
     * calls or assumes its reply is auto-delivered when (for tool-only agents)
     * it would not be.
     */
    slackReplyRelay?: boolean
}

const CATEGORY_HINTS: Record<UnavailableMcpCategory, string> = {
    // `connection_dead` gets its own section (not this hint), but the record
    // must stay total — fall back to the same phrasing if it ever lands here.
    connection_dead: 'disconnected — needs an admin to reconnect',
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

    if (await bundle.exists(rev.id, 'agent.md')) {
        parts.push(await bundle.readText(rev.id, 'agent.md'))
    } else {
        parts.push('(missing agent.md — please add it)')
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
    // Three distinct fixes, three sections:
    //   - linkable        — the ASKER connects their own account (authorizeUrl).
    //   - dead            — a SHARED connection the asker can't touch; only the
    //                       agent's owner/admin can reconnect it, and it won't
    //                       self-heal (so: not "retry shortly").
    //   - broken          — a transient/unknown outage; may recover on its own.
    const linkable = unavailable.filter((u) => u.authorizeUrl)
    const rest = unavailable.filter((u) => !u.authorizeUrl)
    const dead = rest.filter((u) => u.category === 'connection_dead')
    const broken = rest.filter((u) => u.category !== 'connection_dead')
    if (linkable.length > 0) {
        const lines = ['\n\n---\n\n## Connect required', '']
        lines.push(
            "These capabilities need the user to connect (or reconnect) their account before you can use them — the connection is either not set up yet or no longer has the access it needs. When they ask for something one powers (including asking to reconnect), relay the link below as a **markdown link** with a short friendly label (never the bare URL), ask them to click it, then re-ask — don't say it's unavailable:"
        )
        lines.push('')
        for (const u of linkable) {
            lines.push(`- \`${u.id}\`: [Connect ${u.id}](${u.authorizeUrl})`)
        }
        parts.push(lines.join('\n'))
    }
    if (dead.length > 0) {
        const lines = ['\n\n---\n\n## Disconnected integrations', '']
        lines.push(
            "These integrations use a shared connection set up by the agent's owner, and that connection is no longer working (the owner needs to reconnect it in PostHog). This will NOT fix itself and the user can't reconnect it themselves — so do not suggest they retry or sign in. If they ask for something one of these powers, tell them the integration is disconnected and that an administrator/the agent owner needs to reconnect it in PostHog, then carry on with the tools you DO have:"
        )
        lines.push('')
        for (const u of dead) {
            lines.push(`- \`${u.id}\``)
        }
        lines.push('')
        lines.push('Do NOT paste raw error messages, transport URLs, or stack traces into the conversation.')
        parts.push(lines.join('\n'))
    }
    if (broken.length > 0) {
        const lines = ['\n\n---\n\n## Unavailable capabilities', '']
        lines.push(
            'The following MCP servers your spec references failed to open for this session, so their tools are not callable:'
        )
        lines.push('')
        for (const u of broken) {
            lines.push(`- \`${u.id}\` — ${CATEGORY_HINTS[u.category]}`)
        }
        lines.push('')
        lines.push(
            'Continue helping the user with the tools you DO have. If they ask for something only an unavailable server can do, tell them the relevant capability is temporarily unavailable and let them know the agent owner can check the session logs for detail — do NOT paste raw error messages, transport URLs, or stack traces into the conversation.'
        )
        parts.push(lines.join('\n'))
    }

    if (opts.slackReplyRelay) {
        parts.push(
            [
                '\n\n---\n\n## Responding in Slack',
                '',
                'This session is triggered from a Slack thread, and the platform posts your reply for you: every message you finish is delivered to the thread automatically. Just answer in natural language as you normally would — you do NOT need a tool to reply, and you should NOT repeat your answer through a tool (that double-posts).',
                '',
                'Reach for `@posthog/slack-post-message` only when the plain reply cannot express what you need: Block Kit blocks, posting to a different channel, a DM, or editing an earlier message. For everything else, your normal reply IS the Slack message.',
            ].join('\n')
        )
    }

    return parts.join('\n')
}

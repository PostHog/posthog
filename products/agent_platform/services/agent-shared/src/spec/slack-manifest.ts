/**
 * Deterministic Slack app manifest generator.
 *
 * Maps an agent's spec (the slack trigger config + its tools) to a Slack
 * "create an app from a manifest" document. The whole point is that the event
 * subscriptions are derived from the SAME flags the ingress trigger gate reads
 * (`mention_only` / `auto_resume_threads` — see
 * services/agent-ingress/src/triggers/slack.ts), so a config that needs plain
 * `message` events to flow in yields a manifest that subscribes to them — by
 * construction, no manual step to forget.
 *
 * Pure + dependency-injected: the native-tool scope lookup is passed in
 * (`scopesForNativeTool`) because agent-shared can't import agent-tools (cycle).
 * The janitor wires `listNativeTools()` into it.
 */

import type { ToolRef, Trigger } from './spec'

/** Slack app manifest (the subset we populate). Emitted as JSON — Slack's
 *  "create from manifest" accepts JSON as well as YAML. */
export interface SlackAppManifest {
    display_information: { name: string; description?: string }
    features: {
        bot_user: { display_name: string; always_online: boolean }
        /** Only emitted when DMs are enabled — Slack hides the Messages tab
         *  (and so the ability to DM the bot) unless this opts in. */
        app_home?: { messages_tab_enabled: boolean; messages_tab_read_only_enabled: boolean }
    }
    oauth_config: { scopes: { bot: string[] } }
    settings: {
        event_subscriptions: { request_url: string; bot_events: string[] }
        interactivity?: { is_enabled: true; request_url: string }
        org_deploy_enabled: boolean
        socket_mode_enabled: boolean
        token_rotation_enabled: boolean
    }
}

export interface BuildSlackManifestInput {
    /** The agent's triggers — must contain a `slack` trigger. */
    triggers: Trigger[]
    /** The agent's tools — used to union Slack OAuth scopes + detect approvals. */
    tools: ToolRef[]
    /** App display name (from the application). Truncated to Slack's 35-char cap. */
    displayName: string
    /** App description (from the application). Truncated to Slack's 140-char cap. */
    displayDescription?: string
    /** Public events Request URL, or null when no public ingress URL is configured. */
    eventsUrl: string | null
    /** Public interactivity Request URL, or null. */
    interactivityUrl: string | null
    /** Native-tool id → the Slack OAuth scopes it needs (its `requires.provider`
     *  scopes when that provider is `slack`, else `[]`). Injected by the caller
     *  (janitor) since agent-shared can't import agent-tools. */
    scopesForNativeTool: (id: string) => string[]
}

export interface BuildSlackManifestResult {
    manifest: SlackAppManifest
    /** Human reminders the manifest can't enforce (bot must be in-channel, etc.). */
    notes: string[]
}

const EVENTS_URL_PLACEHOLDER = 'https://<set AGENT_INGRESS_PUBLIC_URL>/slack/events'
const INTERACTIVITY_URL_PLACEHOLDER = 'https://<set AGENT_INGRESS_PUBLIC_URL>/slack/interactivity'

// Cap to Slack's char limit. With `ellipsis`, cut at a word boundary + "…" so a
// long description ends cleanly, not mid-word (names/display_name can't — "…"
// isn't in their allowed charset).
function truncate(value: string, max: number, ellipsis = false): string {
    if (value.length <= max) {
        return value
    }
    if (!ellipsis) {
        return value.slice(0, max)
    }
    const slice = value.slice(0, max - 1)
    const lastSpace = slice.lastIndexOf(' ')
    return `${(lastSpace > 0 ? slice.slice(0, lastSpace) : slice).trimEnd()}…`
}

/**
 * Build the Slack manifest for an agent. Throws if the spec has no slack
 * trigger — callers gate on that and surface a clear 400.
 */
export function buildSlackManifest(input: BuildSlackManifestInput): BuildSlackManifestResult {
    const slackTrigger = input.triggers.find((t): t is Extract<Trigger, { type: 'slack' }> => t.type === 'slack')
    if (!slackTrigger) {
        throw new Error('no_slack_trigger')
    }
    const config = slackTrigger.config
    const notes: string[] = []

    // Event subscriptions. `app_mention` is always needed; plain `message`
    // events are needed when the bot reacts to non-mentions (mention_only off)
    // OR resumes threads without a re-mention (auto_resume_threads on). This
    // mirrors the ingress gate exactly.
    const mentionOnly = config.mention_only ?? false
    const autoResumeThreads = config.auto_resume_threads ?? false
    const allowDms = config.allow_direct_messages ?? false
    const needsMessageEvents = mentionOnly === false || autoResumeThreads === true
    const botEvents = ['app_mention']
    if (needsMessageEvents) {
        botEvents.push('message.channels', 'message.groups')
    }
    if (allowDms) {
        botEvents.push('message.im', 'message.mpim')
    }

    // Bot OAuth scopes. Union the Slack scopes declared by the agent's Slack
    // tools, plus what the trigger itself needs.
    const scopes = new Set<string>(['app_mentions:read', 'chat:write'])
    for (const tool of input.tools) {
        // `scopesForNativeTool` returns the tool's Slack scopes only when its
        // declared provider is `slack` (else `[]`), so we no longer special-case
        // the `@posthog/slack-` id prefix — the provider is the source of truth.
        if (tool.kind === 'native') {
            for (const scope of input.scopesForNativeTool(tool.id)) {
                scopes.add(scope)
            }
        }
    }
    if (config.ack_reaction) {
        scopes.add('reactions:write')
    }
    if (needsMessageEvents) {
        // Required to receive message.* events (and the read tools need them too).
        scopes.add('channels:history')
        scopes.add('groups:history')
    }
    if (allowDms) {
        // Required to receive message.im / message.mpim events.
        scopes.add('im:history')
        scopes.add('mpim:history')
    }

    // Interactivity is only used by approval-gated tools (the elevation buttons).
    const hasApprovalGatedTool = input.tools.some(
        (t) => (t.kind === 'native' || t.kind === 'custom') && t.requires_approval === true
    )

    if (!input.eventsUrl) {
        notes.push(
            'This deployment has no public ingress URL (AGENT_INGRESS_PUBLIC_URL is unset), ' +
                'so the Request URL is a placeholder. Set it and regenerate before pasting into Slack.'
        )
    }
    notes.push(
        'Invite the bot to each channel it should listen in — Slack only delivers channel ' +
            'message events to channels the bot has joined.'
    )
    if (allowDms) {
        notes.push("Direct messages enabled — users can DM the bot from the app's Messages tab.")
    }

    const manifest: SlackAppManifest = {
        display_information: {
            name: truncate(input.displayName, 35),
            ...(input.displayDescription ? { description: truncate(input.displayDescription, 140, true) } : {}),
        },
        features: {
            bot_user: { display_name: truncate(input.displayName, 35), always_online: true },
            // Without the Messages tab enabled, users literally can't open a DM
            // with the bot — so this rides along with allow_direct_messages.
            ...(allowDms ? { app_home: { messages_tab_enabled: true, messages_tab_read_only_enabled: false } } : {}),
        },
        oauth_config: { scopes: { bot: [...scopes].sort() } },
        settings: {
            event_subscriptions: {
                request_url: input.eventsUrl ?? EVENTS_URL_PLACEHOLDER,
                bot_events: botEvents,
            },
            ...(hasApprovalGatedTool
                ? {
                      interactivity: {
                          is_enabled: true as const,
                          request_url: input.interactivityUrl ?? INTERACTIVITY_URL_PLACEHOLDER,
                      },
                  }
                : {}),
            org_deploy_enabled: false,
            socket_mode_enabled: false,
            token_rotation_enabled: false,
        },
    }

    return { manifest, notes }
}

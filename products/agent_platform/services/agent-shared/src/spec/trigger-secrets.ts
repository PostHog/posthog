/**
 * Per-trigger-type registry of secrets the trigger expects to find in
 * `AgentApplication.encrypted_env`. Single source of truth shared between:
 *
 *   - **agent-ingress** — trigger handlers look up the value at request time
 *     using the registry's `key` (no spec-side ref to keep in sync).
 *   - **agent-janitor** — freeze-time validation rejects revisions that
 *     declare a trigger whose `required: true` secrets aren't present in
 *     the agent's `encrypted_env`.
 *   - **console UI** — the env editor reads the registry to surface
 *     "Required for this trigger" hints next to the inputs.
 *
 * Storing the contract here (not on the spec) means authors don't pick names
 * and the platform can't drift on what a trigger actually consumes.
 */

import type { TriggerType } from './spec'

export interface TriggerSecretRequirement {
    /** Key the trigger reads from `application.encrypted_env`. Conventional —
     *  authors never name this themselves. */
    key: string
    /** UI label for the env editor. */
    label: string
    /** UI helper text — where to find the value (e.g. a Slack settings page). */
    description: string
    /** When `true`, freeze-time validation rejects the revision if the key is
     *  missing from `encrypted_env`. When `false`, the trigger boots but the
     *  feature that depends on the secret degrades. */
    required: boolean
}

/** Conventional name for the Slack app signing secret. Exported so the slack
 *  trigger handler imports the same constant the registry uses. */
export const SLACK_SIGNING_SECRET_KEY = 'SLACK_SIGNING_SECRET'
/** Conventional name for the Slack bot user OAuth token. Native slack tools
 *  (`@posthog/slack-post-message` etc.) read this via `ctx.secret()` — the
 *  platform deliberately does not use the team-wide Slack OAuth integration. */
export const SLACK_BOT_TOKEN_KEY = 'SLACK_BOT_TOKEN'

export const TRIGGER_REQUIRED_SECRETS: Record<TriggerType, TriggerSecretRequirement[]> = {
    chat: [],
    webhook: [],
    cron: [],
    mcp: [],
    slack: [
        {
            key: SLACK_SIGNING_SECRET_KEY,
            label: 'Slack signing secret',
            description:
                "Your Slack app's signing secret. Find it under Settings → Basic Information → Signing Secret. Required to verify inbound Slack event signatures.",
            required: true,
        },
        {
            key: SLACK_BOT_TOKEN_KEY,
            label: 'Slack bot user OAuth token',
            description:
                "Your Slack app's bot token (starts with `xoxb-`). Find it under Settings → Install App → Bot User OAuth Token after installing the app to your workspace. Used by native slack tools to call the Slack API.",
            required: true,
        },
    ],
}

/**
 * AgentRevision spec — the structural/queryable layer.
 *
 * Lives in the DB as JSONB. The S3 bundle holds the content layer (agent.md,
 * skills tree, per-tool source.ts + compiled.js). See docs/native-refactor.md §1.
 */

import { z } from 'zod'

import type { TriggerMetadata } from '../runtime/trigger-metadata'

/**
 * Canonical model id: `<provider>/<model-id>` (e.g. `anthropic/claude-haiku-4-5`).
 *
 * Reject bare ids at authoring time so we don't freeze a revision the gateway
 * can't serve. `resolveModel` / `acceptedModelIds` operate on the prefixed
 * form; a bare `haiku-4-5` would pass `.min(1)` here, freeze, then fail the
 * very first session with a 400 from the gateway. This regex is the single
 * source of truth for the id format; `gateway-catalog.ts` mirrors it for the
 * runtime servability check.
 */
export const ModelIdSchema = z
    .string()
    .min(1)
    .regex(/^[a-z0-9_-]+\/[a-zA-Z0-9._:-]+$/, 'model id must be "<provider>/<model-id>"')
    .describe(
        'Canonical model id in "<provider>/<model-id>" form, e.g. anthropic/claude-sonnet-4-6. Call the agent-applications-models tool for the list of gateway-served ids; an unserved id freezes but fails the first session.'
    )

/**
 * Auth modes. Auth is a property of the TRIGGER, not the spec — declarative
 * triggers (webhook / chat / mcp) carry their own `auth` block; intrinsic ones
 * (slack / cron) do not. The ingress verifier tries each mode in order; first
 * match wins. Identity (the `SessionPrincipal`) is kept separate from
 * credentials (tokens, held in the `CredentialBroker`).
 */
export const AuthModeSchema = z.discriminatedUnion('type', [
    /**
     * Anonymous — no auth required. **Every** request resolves to an
     * anonymous principal. Genuinely-public agents are rare (a docs
     * site embed, a marketing chatbot). To opt in, the author MUST
     * set `acknowledge_public_exposure: true` — the field exists to
     * make the choice deliberate at spec-authoring time and to give
     * the UI a single flag to render a loud warning against. Skill
     * authoring tools (concierge) treat this as a hard-pause decision
     * point: confirm with the user before adding it to a spec.
     */
    z.object({
        type: z.literal('public'),
        acknowledge_public_exposure: z.literal(true, {
            message:
                'public auth must set acknowledge_public_exposure: true. Public agents accept anonymous requests — confirm this is intentional. If you only need PostHog console / MCP access, use posthog_internal or posthog instead.',
        }),
    }),
    /** A PostHog credential bearer — a Personal API key today, OAuth in future.
     *  Both validate against `/api/users/@me/`; produces a `posthog` principal
     *  + `posthog_api` credential for tools. `scopes` is reserved for future
     *  OAuth scope-gating.
     *
     *  `audience` is the tenant boundary for invocation — who may call a
     *  `posthog`-gated agent:
     *    - `project` (default): the caller must have access to the agent's
     *      OWNING project (team). Tightest; the safe default.
     *    - `organization`: the caller must be a member of the agent's owning
     *      organization (any project within it). Use for a shared agent — e.g.
     *      one "agent builder" used across an org's projects.
     *  Either way the agent still acts AS the caller (their bearer + an explicit
     *  `project_id` per tool), so data access is RBAC-enforced on top of this.
     *  Opening an agent to ANY PostHog user across orgs is deliberately NOT an
     *  option here yet — that needs a dedicated cross-tenant concept. */
    z.object({
        type: z.literal('posthog'),
        scopes: z.array(z.string()).default([]),
        audience: z.enum(['project', 'organization']).default('project'),
    }),
    /** JWT signed with the named encrypted-env secret. Lets a B2B
     *  embedder mint identity tokens for their users without going
     *  through OAuth. Credential available to tools as `self` (the JWT
     *  itself + decoded claims). */
    z.object({
        type: z.literal('jwt'),
        issuer_secret_ref: z.string().min(1),
    }),
    /** Shared secret in a named header. Expected value lives in `encrypted_env`
     *  under `secret_ref`; the spec never carries the secret itself.
     *
     *  Trust model: one secret == one trust principal. Every holder of the
     *  secret is the same principal — you cannot derive forge-resistant
     *  per-caller identity from a credential the holder fully owns. Mint a
     *  distinct secret per upstream integration. For per-caller isolation
     *  among many distinct callers (embedded chat, multi-tenant), use `jwt`
     *  (the upstream signs `sub`, which `principalsMatch` discriminates on). */
    z.object({
        type: z.literal('shared_secret'),
        header: z.string().min(1),
        secret_ref: z.string().min(1),
    }),
    /** PostHog-internal server-to-server token (for Django ↔ ingress). */
    z.object({ type: z.literal('posthog_internal') }),
])

export const AuthConfigSchema = z.object({
    /**
     * Accepted auth modes. First successful match per request wins. Default is
     * the closed `posthog_internal` mode (server-to-server platform tokens
     * only). Public exposure is opt-in and requires
     * `acknowledge_public_exposure: true` — see `AuthModeSchema`.
     */
    modes: z.array(AuthModeSchema).default([{ type: 'posthog_internal' }]),
})

export const TriggerSchema = z.discriminatedUnion('type', [
    /**
     * Slack trigger. These spec flags only control what the INGRESS does with
     * an event once Slack delivers it — they cannot make Slack send an event
     * it isn't subscribed to. For the agent to behave as configured, the Slack
     * app itself must be set up to match:
     *
     *   - Event Subscriptions → Request URL points at the agent's
     *     `slack_events_url`. Interactivity (approval buttons) →
     *     `slack_interactivity_url`.
     *   - Subscribe to bot events:
     *       - `app_mention` — required for @-mention triggering.
     *       - `message.channels` / `message.groups` / `message.im` /
     *         `message.mpim` — required for ANY non-mention message to arrive
     *         (i.e. for `mention_only: false`, or for `auto_resume_threads`
     *         thread follow-ups). If the app only subscribes to `app_mention`,
     *         setting `mention_only: false` changes nothing — Slack never
     *         sends the plain messages.
     *   - OAuth scopes: `app_mentions:read`, `chat:write`, `reactions:write`
     *     (for `ack_reaction` + replies), and `channels:history` /
     *     `groups:history` to receive `message.*` events.
     *   - The bot user must be a MEMBER of each channel — Slack only delivers
     *     `message.*` events for channels the bot has joined.
     *   - `SLACK_SIGNING_SECRET` (verify inbound) and `SLACK_BOT_TOKEN` (call
     *     Slack APIs) must be set in the agent's encrypted env.
     *   - Direct messages (`allow_direct_messages: true`): subscribe to
     *     `message.im` / `message.mpim`, add the `im:history` / `mpim:history`
     *     scopes, and enable the App Home Messages tab (otherwise users can't
     *     open a DM with the bot). The manifest builder emits all three.
     *
     * The session key for a channel/thread is `slack:<channel>:<thread_ts>`
     * (the opening @-mention's `ts` becomes the thread root); every later event
     * in that thread resumes the same session. A DM has no thread, so its
     * session is keyed per-channel (`slack:<channel>`) — one rolling session per
     * DM conversation, idle-reset via `spec.resume` (the janitor closes the
     * `completed` session at its TTL, and the next DM rolls onto a fresh one).
     */
    z.object({
        type: z.literal('slack'),
        config: z.object({
            channel_id: z.string().optional(),
            /**
             * When true, only `app_mention` events (the bot was @-mentioned)
             * are routed into a session. Plain `message` events delivered by
             * Slack — e.g. because the bot subscribed to `message.channels` —
             * are dropped at the trigger. Default false to preserve historical
             * "react to anything in the channel" behaviour for bots that
             * already shipped without the gate.
             *
             * Recommended setup for "@-mention to start, then converse in the
             * thread": `mention_only: true` + `auto_resume_threads: true`.
             */
            mention_only: z.boolean().default(false),
            /**
             * Relaxes `mention_only` for replies in threads where the bot
             * already holds an open session — i.e. the user @-mentioned the
             * bot to start the thread, and is now continuing the conversation
             * without re-@-mentioning every turn. Implemented as: when
             * `mention_only` is true, the trigger normally drops non-mention
             * `message` events; with `auto_resume_threads`, those events ARE
             * routed when `thread_ts` matches an existing session's
             * external_key. Sessions seeded this way are flagged as
             * `mention: false` in the seed message so the model can judge
             * whether the message is actually addressed to it. No effect when
             * `mention_only` is false (everything's already accepted). Default
             * false for back-compat.
             */
            auto_resume_threads: z.boolean().default(false),
            /**
             * Who may advance a thread once it's open. Every Slack session is
             * owned by the principal who opened it (the @-mentioner). By
             * default (`false`) only that user can drive the thread: a reply
             * from a different Slack user fails the per-session ACL check and
             * is recorded as an elevation request rather than advancing the
             * session.
             *
             * Set `true` to let ANY user in a `trusted_workspaces` workspace
             * post into the thread and advance the session — a shared/team
             * concierge thread where colleagues chime in. The `trusted_workspaces`
             * gate still applies (untrusted workspaces are rejected upstream),
             * and every message still records its real sender for audit; this
             * only waives the "same user as the owner" requirement. Default
             * false (owner-only).
             */
            allow_workspace_participants: z.boolean().default(false),
            /**
             * Emoji name (no surrounding colons, e.g. `"eyes"` or
             * `"thinking_face"`) that the ingress posts as an immediate
             * `reactions.add` against the inbound message, BEFORE returning
             * the event ack to Slack. Gives the user feedback within Slack's
             * 3s window even when the runner takes longer to claim the
             * session + produce a first turn. Fire-and-forget: failures
             * (revoked token, channel-not-found, already-reacted) are
             * silently swallowed — the gate is "session enqueued", not
             * "reaction landed". When unset, no ack reaction.
             */
            ack_reaction: z.string().optional(),
            /**
             * Opt-in DM surface. When true, the bot also handles direct
             * messages (`channel_type: "im"`) and group DMs
             * (`channel_type: "mpim"`), not just channel mentions. Drives both
             * the manifest builder (subscribes `message.im` / `message.mpim`,
             * adds `im:history` / `mpim:history`, enables the App Home Messages
             * tab) and the ingress gate (a DM arriving while this is false is
             * dropped). A DM is inherently directed at the bot, so it bypasses
             * `mention_only` and is keyed per-channel (`slack:<channel>`) for
             * one rolling session per conversation. Default false.
             */
            allow_direct_messages: z.boolean().default(false),
            /**
             * Required. Workspaces (Slack team ids, e.g. "T01ABC") allowed to
             * invoke this agent. Use the literal string `"*"` to opt into an
             * open-to-any-workspace policy (B2C-style public bot). Authors
             * MUST make the choice explicitly — there is no implicit
             * "any-workspace" default.
             */
            trusted_workspaces: z.union([z.array(z.string()).min(1), z.literal('*')]),
        }),
    }),
    z.object({
        type: z.literal('webhook'),
        config: z.object({
            path: z.string(),
        }),
        auth: AuthConfigSchema,
    }),
    z.object({
        type: z.literal('cron'),
        config: z.object({
            /**
             * Human + machine handle for this cron job. Unique within the
             * agent's `triggers[]` (validated at freeze time). Surfaces as
             * `trigger_metadata.cron_name` on the session row + in
             * `trigger_metadata.cron_name` for placeholder expansion in
             * `external_key` and `prompt`. Lowercase alphanumeric + hyphens.
             */
            name: z
                .string()
                .min(1)
                .regex(/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/, {
                    message: 'cron name must be lowercase alphanumeric with hyphens, no leading/trailing hyphen',
                }),
            /** Cron expression. Validated against `cron-parser` at freeze time. */
            schedule: z.string().min(1),
            /** IANA timezone — DST handling delegated to `cron-parser`. */
            timezone: z.string().default('UTC'),
            /**
             * The task to communicate to the agent when the cron fires —
             * arrives as a user-role message at session start. Supports the
             * shared placeholder set (`fired_at:iso`, `fired_at:date`,
             * `fired_at:week`, `schedule`, `cron_name`). Capped at 4096 chars
             * to keep the prompt diff-reviewable.
             */
            prompt: z.string().min(1).max(4096),
            /**
             * Optional. When set, firings dedupe / append onto the same
             * session via the existing `external_key` resume path; same
             * placeholder set as `prompt`. When absent (default), every
             * firing creates a fresh session.
             */
            external_key: z.string().optional(),
            /**
             * What to do when the janitor missed scheduled firings (downtime,
             * restart, deploy). `most_recent` (default) fires the latest
             * missed firing once; `all` fires every missed firing in the
             * window; `skip` drops them. See plan §7.
             */
            catch_up: z.enum(['all', 'most_recent', 'skip']).default('most_recent'),
            /**
             * Hard cap on how far back catch-up will look. Default 1 hour,
             * max 7 days (604800s). Bounded regardless of `catch_up` mode.
             */
            max_catch_up_age_seconds: z
                .number()
                .int()
                .min(1)
                .max(7 * 86400)
                .default(3600),
        }),
    }),
    z.object({
        type: z.literal('chat'),
        config: z
            .object({
                /**
                 * When true, `/send` to a `closed` session reopens it (state
                 * → queued, message appended to pending_inputs) instead of
                 * returning 410. Default false — `meta-end-session` is
                 * normally a hard close. Has no effect on `failed` sessions
                 * (those stay terminal). See the session-restart redesign.
                 */
                allow_restart: z.boolean().default(false),
            })
            .default({ allow_restart: false }),
        auth: AuthConfigSchema,
    }),
    z.object({
        type: z.literal('mcp'),
        config: z
            .object({
                /** Mirror of the chat trigger flag — see above. */
                allow_restart: z.boolean().default(false),
            })
            .default({ allow_restart: false }),
        auth: AuthConfigSchema,
    }),
])

/**
 * Approval `type` — who clears a gated call. Two independent authorities:
 *   - `principal` (default) — the session's principal: whoever drove this
 *     session. A *generic identity match* (slack user id / jwt sub / posthog
 *     uuid == the session principal), NOT a PostHog-authority check, so it works
 *     for a Slack or embedded-app asker with no PostHog account. Decided via the
 *     lightweight ingress decision API (a Slack button, a client tool, or the
 *     PostHog Code approval card).
 *   - `agent` — the agent's owning-team admins (org-membership ADMIN level on
 *     the owning team; see Django `_require_team_admin`). The one intrinsically-
 *     PostHog authority; decided only in the authenticated console / approvals
 *     inbox. (A creator who isn't a team admin can't decide today — kept simple
 *     until a finer owner grant exists.)
 *
 * Neither auto-dispatches: the owner/principal being the *asker* is not consent
 * to the specific call the model emitted (prompt injection in content the agent
 * read could steer it), so every gated call queues for an explicit human action.
 */
export const ApprovalTypeSchema = z.enum(['principal', 'agent'])
export type ApprovalType = z.infer<typeof ApprovalTypeSchema>

/**
 * Map a pre-rebuild `approvers[]` scope to the new `type`, so specs frozen
 * before the principal/agent split keep parsing. `team_admins` was the owner
 * authority → `agent`; `session_principal` → `principal`.
 */
function legacyApproversToApprovalType(approvers: unknown): ApprovalType | undefined {
    if (!Array.isArray(approvers)) {
        return undefined
    }
    if (approvers.includes('team_admins')) {
        return 'agent'
    }
    if (approvers.includes('session_principal')) {
        return 'principal'
    }
    return undefined
}

/**
 * Approval policy attached to a tool ref / MCP tool entry. Authoritative
 * defaults live here — the dispatcher reads `approval_policy` directly after Zod
 * parsing, so omitting fields falls through to these values.
 */
export const ApprovalPolicySchema = z.preprocess(
    (raw) => {
        // Back-compat: pre-rebuild specs carry `approvers[]` + `allow_agent_approver`
        // instead of `type`. Derive `type` from the old scope and drop the legacy
        // keys so old frozen revisions still validate.
        if (
            raw &&
            typeof raw === 'object' &&
            !Array.isArray(raw) &&
            (raw as Record<string, unknown>).type === undefined
        ) {
            const obj = { ...(raw as Record<string, unknown>) }
            const type = legacyApproversToApprovalType(obj.approvers)
            delete obj.approvers
            delete obj.allow_agent_approver
            return type ? { ...obj, type } : obj
        }
        return raw
    },
    z.object({
        type: ApprovalTypeSchema.default('principal'),
        allow_edit: z.boolean().default(false),
        ttl_ms: z
            .number()
            .int()
            .min(60_000) // 1 minute
            .max(7 * 24 * 60 * 60 * 1000) // 7 days
            .default(24 * 60 * 60 * 1000), // 24h
    })
)

export const DEFAULT_APPROVAL_POLICY = {
    type: 'principal' as const,
    allow_edit: false,
    ttl_ms: 24 * 60 * 60 * 1000,
}

/**
 * Per-tool approval level for an MCP connection: the effective level of a remote
 * tool decides what the runner does with it.
 *   - `allow`   — exposed, runs without approval.
 *   - `approve` — exposed, every call parks for approval (the entry's
 *                 `approval_policy` decides who/ttl).
 *   - `deny`    — NOT exposed to the model at all.
 *
 * Used both as the connection-wide default (`McpRef.default_tool_approval`) and
 * as a per-tool override (`McpToolEntry.level`). Effective level for a tool =
 * its override `level` ?? the connection default. A connection with
 * `default_tool_approval: 'deny'` + per-tool `allow` overrides is a strict
 * allowlist. See `services/agent-runner/src/loop/build-agent-tools.ts`
 * (exposure) and `mcp-tool-lookup.ts` (approval).
 */
export const ToolApprovalLevelSchema = z.enum(['allow', 'approve', 'deny'])
export type ToolApprovalLevel = z.infer<typeof ToolApprovalLevelSchema>

export const ToolRefSchema = z.discriminatedUnion('kind', [
    z.object({
        kind: z.literal('native'),
        id: z.string(),
        requires_approval: z.boolean().default(false),
        approval_policy: ApprovalPolicySchema.default(DEFAULT_APPROVAL_POLICY),
        // Native tools declare their credential provider intrinsically (the tool
        // definition's `requires.provider`), so the spec ref carries no identity
        // field — the runtime reads it from the registry.
    }),
    z.object({
        kind: z.literal('custom'),
        id: z.string(),
        path: z.string(),
        requires_approval: z.boolean().default(false),
        approval_policy: ApprovalPolicySchema.default(DEFAULT_APPROVAL_POLICY),
        // The single identity provider (id from spec.identity_providers[]) this
        // custom tool acts as. Unlinked → the dispatch wrapper relays an
        // auth_required link. One provider per tool by design.
        requires_identity: z.string().optional(),
    }),
    // NOTE: the registry-pin shape `{ kind: 'custom_template', from_template,
    // alias, version }` is a *draft-only* authoring shape. It is deliberately
    // NOT in this runtime union: freeze reshapes it into the `custom` variant above
    // before the runner ever parses the spec, and the dispatcher assumes
    // every non-`client` tool carries `requires_approval`.
    /**
     * **Client-fulfilled tool.** The agent author declares the tool fully
     * inline (id + description + args_schema); the connecting client (browser
     * dock, IDE MCP host, etc.) declares which ids it can execute this session
     * via `supported_client_tools` in the /run body (stashed on the session's
     * `trigger_metadata`). The runner gates EXPOSURE on it:
     *
     *   - id in `supported_client_tools` → exposed to the model.
     *   - NOT declared, `required: false` (default) → hidden from the model
     *     surface; write agent.md to degrade gracefully (text-only narration).
     *   - NOT declared, `required: true` → session open fails with
     *     `client_tool_unsupported`.
     *
     * Non-chat surfaces (Slack, cron, webhook, MCP) declare nothing, so client
     * tools — including interactive punch-outs like `connect_mcp` /
     * `set_secret` — are simply not exposed there; the model never sees a tool
     * it can't get a result for.
     *
     * Dispatch path: when the model calls the tool, the runner emits a
     * `client_tool_call` session event carrying the args + a call_id;
     * the client executes locally and POSTs the result to
     * `/sessions/<id>/client_tool_result`. Interactive tools park the session
     * until that result arrives.
     */
    z.object({
        kind: z.literal('client'),
        /**
         * Tool id the model sees. Author-chosen; must not collide with
         * other tools in the same spec. Convention: short snake_case
         * names (`focus`, `toast`, `get_context`) — no required prefix.
         */
        id: z.string().min(1),
        /**
         * Human-readable + model-readable description. Same as native
         * tool descriptions; this is the primary signal the model uses
         * to decide when to call the tool.
         */
        description: z.string().min(1),
        /**
         * JSON Schema for the tool's args. Held as a free-form object
         * because spec authors define their own shape per tool — the
         * runner doesn't introspect it.
         */
        args_schema: z.record(z.string(), z.unknown()).default({}),
        /**
         * When false (the default), missing client support → tool hidden,
         * session proceeds. When true, missing client support → session
         * open fails.
         */
        required: z.boolean().default(false),
        /**
         * Per-call timeout in ms. Only consulted when `interactive` is
         * false; interactive tools park the session persistently and
         * have no in-process timeout. Default 5s for sync UI tools.
         */
        timeout_ms: z.number().int().positive().max(600_000).default(5_000),
        /**
         * Park the session and resume on `/send` (client_tool_result
         * variant) instead of awaiting the bus result in-process. Use
         * for render-style tools whose UI needs unbounded user time.
         */
        interactive: z.boolean().default(false),
    }),
])

/**
 * Per-tool entry for an MCP ref — overrides the connection defaults for one
 * tool. `level` sets allow / approve / deny (vs `default_tool_approval`);
 * `approval_policy` optionally pins WHO approves + ttl for an `approve` tool
 * (vs the connection's `approval_policy`). A tool with no entry takes the
 * connection defaults.
 *
 * Per-tool `approval_policy` is what lets a designer route most approvals to the
 * asker (`type: 'principal'`) while sending a specific sensitive tool to the
 * agent's owning team (`type: 'agent'`) — and it's mandatory for tools an agent
 * can call with no principal present (cron/webhook), where a principal approval
 * is undeliverable.
 *
 * The runner looks the entry up by name when building/gating the model-visible
 * `<prefix>__<remoteName>` tool — see
 * `services/agent-runner/src/loop/mcp-tool-lookup.ts` + `build-agent-tools.ts`.
 */
export const McpToolEntrySchema = z.object({
    /** Raw remote tool name (pre-prefix). Must match an entry from `client.listTools()`. */
    name: z.string().min(1),
    /** Override of the connection's `default_tool_approval` for this tool. */
    level: ToolApprovalLevelSchema,
    /** Override of the connection's `approval_policy` for this tool (who approves
     *  + ttl). Only consulted when the effective level is `approve`. */
    approval_policy: ApprovalPolicySchema.optional(),
})

/**
 * Runtime MCP servers an agent connects to at session start. The runner opens
 * one client per entry, exposes each remote tool as a regular `AgentTool` to
 * pi-ai (name-prefixed `<id>__<toolName>`), and routes dispatch back through
 * the open client.
 *
 * Single shape today: a third-party MCP server reachable over HTTP.
 * `auth.provider` references a `spec.identity_providers[]` entry — a
 * per-principal OAuth identity, stamped as the asker's bearer (gates into
 * auth_required if unlinked). `secrets[]` + `headers` is the simpler
 * bring-your-own-token case, resolved through the same encrypted-env path the
 * agent's main `spec.secrets` uses. `id` is the tool-name prefix.
 * `default_tool_approval` sets the connection-wide level; `tools[]` overrides it
 * per tool (`{ name, level }`).
 *
 * The `kind: 'agent'` variant (agent-to-agent MCP composability) was removed
 * in favour of a single flat shape — `agent-as-mcp-server.md` will re-add it
 * when a concrete consumer lands.
 */
export const McpRefSchema = z
    .object({
        /**
         * Stable id within the spec. Tool-name prefix at runtime —
         * `<id>__<toolName>` is what the model sees so it can tell which MCP
         * a tool came from. Must be unique across `spec.mcps[]`.
         */
        id: z
            .string()
            .min(1)
            // The runtime tool-name prefix is `<id>__<remoteName>` and the
            // approval lookup splits on the FIRST `__` (mcp-tool-lookup.ts). An
            // id that itself contains `__` misroutes the split → the per-tool
            // approval gate silently never fires. Forbid the separator.
            .refine((id) => !id.includes('__'), {
                message: "mcps[].id must not contain '__' (it is the tool-name prefix separator)",
            }),
        url: z.string().url(),
        /**
         * Credential model for this server — REQUIRED, the explicit discriminator the
         * runtime and the authoring UI branch on (rather than inferring it from which
         * of `connection`/`auth`/`secrets` happens to be set):
         *   - `'agent'`     — ONE shared credential every asker reuses, supplied
         *     either by a `connection` (mcp_store installation) or a bring-your-own
         *     static token in `secrets` + `headers`. No `auth.provider`.
         *   - `'principal'` — each asker acts as themselves via `auth.provider`
         *     (a per-asker linked identity). No `connection`.
         * The `superRefine` below pins the credential fields to the kind so intent
         * and wiring can't drift.
         */
        kind: z.enum(['agent', 'principal']),
        /**
         * Native MCP connection: the id of an `mcp_store` `MCPServerInstallation` an
         * owner connected once (OAuth incl. DCR, or api-key). When set, the runner
         * loads the bearer from that row (refreshing on expiry) and ignores
         * `auth`/`secrets`/`headers` — ONE shared credential for every asker. `url`
         * stays required (UI-filled); the installation row is the source of truth.
         * Agent-kind only.
         */
        connection: z.string().min(1).optional(),
        /**
         * Connection-wide default approval level (per-agent tool-permission model) —
         * REQUIRED. Every remote tool's effective level = its `tools[].level`
         * override ?? this default; the tool is exposed unless its effective level
         * is `deny`, and gated when `approve`. A curated allowlist is
         * `'deny'` + per-tool `level: 'allow'`. The agent-config UI writes
         * `'approve'` here when an MCP is first attached.
         */
        default_tool_approval: ToolApprovalLevelSchema,
        /**
         * Approval policy (who approves + ttl) for any tool whose effective level is
         * `approve`. Defaults to the principal/24h policy.
         */
        approval_policy: ApprovalPolicySchema.optional(),
        auth: z
            .object({
                /** Per-principal identity provider (id from `spec.identity_providers[]`):
                 *  stamps the linked user's bearer, gates into auth_required if unlinked. */
                provider: z.string().optional(),
            })
            .optional(),
        /**
         * Per-MCP secret names. Resolved at session start through the same
         * encrypted-env path as the agent's main `spec.secrets`. The runner
         * substitutes `${name}` placeholders in the URL + auth headers before
         * opening the client; the plaintext never leaves the runner process.
         */
        secrets: z.array(z.string()).default([]),
        /**
         * Author-supplied request headers stamped on every outgoing MCP request.
         * Values may reference `${NAME}` from `secrets[]`; the runner substitutes
         * the plaintext value before opening the MCP client, so the secret never
         * leaves the runner process. Same substitution shape as
         * `@posthog/http-request`'s `headers` — the parallel is intentional so
         * authors can use the same mental model for "bring my own bearer token"
         * against either a typed MCP catalog or a raw HTTP API.
         *
         * Use this for the bring-your-own-token case (paste a PAT once, reference
         * it as `${TOKEN}` in `Authorization: 'Bearer ${TOKEN}'`). For OAuth, use
         * `auth.provider` instead; provider-stamped headers compose with
         * author-supplied headers — explicit author entries win on duplicate
         * keys, matching `http-request`'s "caller-set values are not silently
         * overwritten" rule.
         */
        headers: z.record(z.string(), z.string()).optional(),
        /**
         * Per-tool overrides of `default_tool_approval`. Each entry's `level` sets
         * that tool to allow/approve/deny; a tool with no entry takes the default.
         * Omitted/empty = every tool takes the connection default.
         *
         * Names must be unique within the array — a duplicate would be a silent
         * first-match-wins footgun, so reject it at parse time.
         */
        tools: z
            .array(McpToolEntrySchema)
            .optional()
            .refine(
                (entries) => {
                    if (!entries) {
                        return true
                    }
                    const seen = new Set<string>()
                    for (const e of entries) {
                        if (seen.has(e.name)) {
                            return false
                        }
                        seen.add(e.name)
                    }
                    return true
                },
                { message: 'mcps[].tools[] entries must have unique names' }
            ),
    })
    .superRefine((ref, ctx) => {
        // Pin the credential fields to the declared kind so the runtime resolution
        // (connection → shared bearer; auth.provider → per-asker identity) and the
        // authoring UI can't disagree with the stated intent.
        if (ref.kind === 'principal') {
            if (!ref.auth?.provider) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    path: ['auth', 'provider'],
                    message: "mcps[].kind 'principal' requires auth.provider (a per-asker linked identity)",
                })
            }
            if (ref.connection) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    path: ['connection'],
                    message:
                        "mcps[].kind 'principal' must not set connection (that is an agent-level shared credential)",
                })
            }
        } else if (ref.auth?.provider) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                path: ['auth', 'provider'],
                message: "mcps[].kind 'agent' must not set auth.provider (use a connection or secrets + headers)",
            })
        }
    })

export const SkillRefSchema = z.object({
    id: z.string(),
    path: z.string(),
    /**
     * Short summary shown in the system-prompt skill index. The model decides
     * whether to call `@posthog/load-skill` based on this description, so it
     * should describe WHAT the skill teaches the agent and WHEN to load it.
     */
    description: z.string().optional(),
    /**
     * Registry lineage for a skill pinned from an `AgentSkillTemplate`.
     * Present on a draft spec; at freeze the Django side resolves
     * `from_template` at the requested `version` (or latest), assembles the
     * spec-compliant `skills/<alias>/SKILL.md` into the bundle, and stamps
     * `id`/`path` from `alias`. These ride through on the frozen spec so the
     * registry "Used by" view can correlate. The runner ignores them — it
     * reads `id`/`path` only.
     */
    from_template: z.string().optional(),
    alias: z.string().optional(),
    version: z.number().int().min(1).optional(),
    // Immutable per-version row id of the resolved store skill — the exact
    // provenance anchor, stamped at freeze. Optional so older frozen specs parse.
    source_version_id: z.string().optional(),
})

/**
 * A `spec.secrets[]` entry. The bare-string form names a secret that's
 * resolvable (its value lives in `encrypted_env`) but carries NO authority to
 * be sent over the wire by `@posthog/http-request` — substitution refuses at
 * runtime with `secret_no_host_binding`. To grant network-egress authority,
 * use the object form and pin the secret to a fixed set of hosts.
 *
 * `allowed_hosts[]` entries:
 *   - `"slack.com"` — exact host match (lowercase, no port).
 *   - `"*.example.com"` — suffix wildcard: matches `foo.example.com`,
 *     `a.b.example.com`, but NOT bare `example.com`.
 *
 * Bound this way, a model-injected `${SLACK_BOT_TOKEN}` against
 * `https://attacker.example/x` is refused before the request goes out — the
 * secret is bound to `slack.com`, not the attacker host. Mirrors the
 * per-integration host binding `mcp-clients.ts` enforces on OAuth bearers.
 */
export const SecretRefSchema = z.union([
    z.string().min(1),
    z.object({
        name: z.string().min(1),
        allowed_hosts: z.array(z.string().min(1)).min(1),
    }),
])

export const SpecLimitsSchema = z.object({
    max_turns: z.number().int().positive().default(50),
    max_tool_calls: z.number().int().positive().default(200),
    max_wall_seconds: z
        .number()
        .int()
        .positive()
        .default(15 * 60),
    /**
     * Hard memory cap for the per-session sandbox in MiB. Modal honors as
     * `memoryLimitMiB`; Docker as `--memory`. Default 512 MiB — same shape as
     * the in-process default. Bump for tools that load large model artifacts
     * or process big payloads.
     */
    max_memory_mb: z.number().int().positive().max(16384).default(512),
    /**
     * CPU reservation for the per-session sandbox in (fractional) cores.
     * Modal honors as `cpu`; Docker as `--cpus`. Default 0.25 — most custom
     * tools are I/O-bound (HTTP, file reads). Bump for compute-bound tools
     * (image processing, parsing, anything CPU-pinned).
     */
    max_cpu_cores: z.number().positive().max(8).default(0.25),
    // Per-turn provider max_tokens. Unset → reasoning-aware default in runner.
    // Clamped at request time to model.maxTokens + operator override.
    max_output_tokens: z.number().int().positive().max(200_000).optional(),
    /**
     * Cap on open (queued) approval requests per session. A model looping on
     * an approval-gated tool can otherwise flood approvers — Slack posts per
     * queued row, console badge inflation — because args-hash dedupe only
     * collapses identical calls, not distinct-args floods. At the cap,
     * further gated calls return a synthetic `approval_budget_exhausted`
     * error to the model instead of queueing. Decisions and TTL expiry free
     * budget; an identical re-ask dedupes onto its existing row and is
     * always allowed.
     */
    max_open_approvals: z.number().int().positive().max(100).default(10),
})

export type AuthMode = z.infer<typeof AuthModeSchema>
export type AuthModeType = AuthMode['type']
export type AuthConfig = z.infer<typeof AuthConfigSchema>

/**
 * Normalized reasoning-effort knob. Matches pi-ai's `ThinkingLevel` exactly,
 * so the runner can forward `spec.reasoning` straight to
 * `completeSimple()` without translation. Provider-specific mappings
 * (Anthropic extended thinking, OpenAI o-series, Gemini thinking) are
 * handled inside pi-ai. Omitting the field uses the provider default —
 * important so existing agents don't get reasoning charges they didn't
 * opt into.
 */
export const ReasoningEffortSchema = z
    .enum(['minimal', 'low', 'medium', 'high', 'xhigh'])
    .describe(
        'Reasoning/thinking effort budget. minimal = no deliberation (fastest, cheapest); low/medium/high add deliberation tokens and per-turn cost; xhigh = maximal (research-grade, roughly 5-10x the per-turn cost). Omit for the provider default.'
    )

/** One model in a manual priority list; per-entry `reasoning` overrides the spec default. */
export const ModelEntrySchema = z.object({
    model: ModelIdSchema,
    reasoning: ReasoningEffortSchema.optional().describe(
        'Per-model reasoning effort override (else the spec default).'
    ),
})

/** Quality/cost level for `auto` policy; mapped to a maintained model list (below). */
export const ModelLevelSchema = z
    .enum(['low', 'medium', 'high'])
    .describe(
        'Quality/cost tier for auto. low = cheapest (short, formulaic, no-reasoning jobs); medium = balanced default (multi-step but bounded); high = top-tier (long, branching, reasoning-heavy). Resolved to a priority-ordered cross-provider model list at session start.'
    )

/**
 * How the runner treats the priority list across a session's turns.
 *
 *  - `cost` (default): the first turn walks the list until a model answers, then
 *    pins that model for the rest of the session — every later turn uses ONLY it,
 *    no cross-model failover. One provider per session keeps its prompt cache warm
 *    (cache reads are ~0.1–0.5× of full input), which dominates multi-turn cost.
 *    The trade: if the pinned model goes down mid-session the turn fails (after
 *    pi-ai's same-provider retries) rather than switching — switching a large
 *    cached session to a cold provider re-reads the whole context at full price.
 *  - `availability`: the runner still leads with the last-served model (sticky, so
 *    it doesn't thrash) but DOES fail over to the next model on failure, trading
 *    that cold-cache re-read for keeping the session alive.
 */
export const ModelOptimizeForSchema = z
    .enum(['cost', 'availability'])
    .describe(
        'Session model stability vs. resilience. cost (default): the first turn pins a working model for the whole session, keeping the provider prompt cache warm (cache reads roughly 0.1-0.5x of full input) and never failing over mid-session; if the pinned model goes down the turn fails rather than cold-re-reading context on another provider. availability: fail over to the next model on failure, surviving an outage at the cost of a one-time cold re-read. Prefer cost for long/expensive sessions, availability where uptime matters more than spend.'
    )

/** `auto`: platform resolves `level` to a priority-ordered list at runtime.
 *  `manual`: author's explicit priority list.
 *  `optimize_for` (both): session model stability vs. resilience — see above. */
export const ModelPolicySchema = z
    .discriminatedUnion('mode', [
        z.object({
            mode: z.literal('auto'),
            level: ModelLevelSchema.default('medium'),
            reasoning: ReasoningEffortSchema.optional(),
            optimize_for: ModelOptimizeForSchema.default('cost'),
        }),
        z.object({
            mode: z.literal('manual'),
            models: z
                .array(ModelEntrySchema)
                .min(1)
                .describe(
                    'Explicit priority-ordered fallback list — the runner tries entries in order, primary first. Order it provider-diverse so one provider outage degrades to the next vendor instead of failing.'
                ),
            optimize_for: ModelOptimizeForSchema.default('cost'),
        }),
    ])
    .describe(
        'How this agent selects its model. auto (default): pick a quality/cost level and the platform resolves it to a maintained, priority-ordered, cross-provider list at runtime — rides model upgrades and cross-provider fallback for free. manual: give an explicit priority-ordered models list (primary first); opts out of platform upgrades, so use only when a specific model is required.'
    )

/** `auto` level → priority-ordered, cross-provider list (also the fallback chain).
 *  The curated grouping layer over the gateway catalog: ids here MUST be
 *  gateway-served. `validateModelLevels` (gateway-catalog.ts) guards that in
 *  CI; the runner filters this against the live catalog at session start. */
export const MODEL_POLICY_LEVELS: Record<z.infer<typeof ModelLevelSchema>, readonly string[]> = {
    low: ['anthropic/claude-haiku-4-5', 'openai/gpt-5-mini'],
    medium: ['anthropic/claude-sonnet-4-6', 'openai/gpt-5'],
    high: ['anthropic/claude-opus-4-7', 'openai/gpt-5-pro'],
}

/**
 * Author-facing knobs for the framework-injected system-prompt preamble.
 */
export const FrameworkPromptSectionSchema = z.enum([
    /** Plan §3.1 — meta-tool decision rules. */
    'meta_tool_guidance',
    /** Plan §3.2 — `completed` vs `closed` contract. */
    'state_contract',
    /** Plan §3.3 — tool failure recovery flow. */
    'tool_failure_guidance',
    /** Plan §3.4 — approval-gated tool result envelope handling. */
    'approval_guidance',
    /** Plan §3.5 — extended-reasoning hint (only injected when spec.reasoning ∈ {high, xhigh}). */
    'reasoning_hint',
])

export const FrameworkPromptConfigSchema = z.object({
    /**
     * Sections to omit from the framework preamble. Reviewer-discoverable
     * (typed + validated at freeze time) escape hatch — see plan §7.4.
     * Unknown values are rejected by the enum.
     */
    omit: z.array(FrameworkPromptSectionSchema).default([]),
    /**
     * Pin the framework preamble version. When unset (default), the
     * runner uses the latest version. When set, the runner renders the
     * preamble as it was at that version — reproducibility escape hatch
     * for authors who don't want a platform upgrade to change frozen
     * revisions. See plan §7.3. Don't expect this to see much use.
     */
    version_pin: z.number().int().positive().optional(),
})

/**
 * Per-agent resumability config. v0 covers only the
 * per-agent TTL on `completed` sessions; compaction + `suspended` state
 * are deferred.
 *
 * `enabled: false` (the default) preserves today's behaviour: the janitor
 * closes idle `completed` sessions at the platform-wide
 * `idleCompletedThresholdMs` (24h). With `enabled: true` the platform
 * defers closing until the per-agent `max_completed_age_ms` is hit,
 * letting a Slack assistant watch a thread for a whole sprint or a
 * weekly cron agent stay reachable across multiple fires.
 */
export const ResumeConfigSchema = z.object({
    enabled: z.boolean().default(false),
    /**
     * Override the platform-wide `completed → closed` sweep TTL. Default
     * 7 days; agents can dial up to whatever the platform admin allows.
     * Has no effect when `enabled: false`.
     */
    max_completed_age_ms: z
        .number()
        .int()
        .positive()
        .default(7 * 24 * 60 * 60 * 1000),
})

/**
 * A per-app identity provider users can link against. Two kinds:
 *   - `posthog` — managed: on promote the backend provisions a normal,
 *     user-consented OAuthApplication for the agent's org and injects its
 *     `client_id` here (the author supplies nothing but optional scopes).
 *     Linking runs PostHog's standard consent flow, so the user explicitly
 *     authorises the agent to act as them.
 *   - `oauth2`  — bring-your-own: the author registers an OAuth app at a third
 *     party (GitHub, Linear, the `dogs` test IdP), points its redirect at our
 *     callback, and supplies endpoints + client_id + a `client_secret_ref`
 *     (a key in the agent's encrypted_env). One generic provider serves them all.
 */
export const IdentityProviderConfigSchema = z.discriminatedUnion('kind', [
    z.object({
        kind: z.literal('posthog'),
        id: z.string().min(1).default('posthog'),
        scopes: z.array(z.string()).default([]),
        /** Who the credential acts as. Only `principal` (per-asker) is accepted:
         *  the `agent` binding (one credential shared by the whole agent) isn't
         *  implemented yet, so it's rejected at the schema until the app-scoped
         *  credential shape lands. The runtime seam still exists (resolve throws
         *  `agent_binding_not_implemented`) for when it does. */
        binding: z.enum(['principal']).default('principal'),
        /** Backend-injected on promote (the provisioned OAuthApplication's
         *  client_id). Author never sets it; absent until the agent is promoted. */
        client_id: z.string().optional(),
    }),
    z.object({
        kind: z.literal('oauth2'),
        id: z.string().min(1),
        binding: z.enum(['principal']).default('principal'),
        authorize_url: z.string().url(),
        token_url: z.string().url(),
        client_id: z.string().min(1),
        /** Key in encrypted_env holding the client secret. Omit for public PKCE clients. */
        client_secret_ref: z.string().optional(),
        scopes: z.array(z.string()).default([]),
        /** Userinfo endpoint, used for the email cross-check warn at link time. */
        userinfo_url: z.string().url().optional(),
    }),
])
export type IdentityProviderConfig = z.infer<typeof IdentityProviderConfigSchema>

export const AgentSpecSchema = z.object({
    /** Model selection: auto level (default) or manual priority list. Resolve via `modelPolicyToList`. */
    models: ModelPolicySchema.default({ mode: 'auto', level: 'medium', optimize_for: 'cost' }),
    triggers: z
        .array(TriggerSchema)
        .describe(
            'How sessions start. Each entry is one trigger (a discriminated union on type: slack, webhook, cron, chat, mcp); an agent can be reachable several ways. Empty = no external triggers (preview/manual runs only).'
        )
        .default([]),
    tools: z
        .array(ToolRefSchema)
        .describe(
            'Tools the agent can call. kind native = @posthog/* built-ins (call the agent-native-tools-list tool for valid ids), custom = author-written TypeScript, client = fulfilled by the connecting app. Empty = no tools.'
        )
        .default([]),
    mcps: z
        .array(McpRefSchema)
        .describe(
            'External MCP servers the agent connects to at session start. Each remote tool is exposed to the model name-prefixed by the entry id; auth.provider links a per-user identity, secrets/headers cover bring-your-own-token.'
        )
        .default([]),
    skills: z
        .array(SkillRefSchema)
        .describe(
            'Skill references (id + path) listed in the system-prompt index; the model loads one on demand. Server-derived at freeze — set these via the skill-refs endpoints, not authored inline.'
        )
        .default([]),
    identity_providers: z
        .array(IdentityProviderConfigSchema)
        .describe(
            'Identity providers users can link against so the agent can act AS the user (the credential axis). kind posthog = managed (provisioned on promote), oauth2 = bring-your-own third-party app.'
        )
        .default([]),
    secrets: z
        .array(SecretRefSchema)
        .describe(
            'Secret names this agent can resolve from its encrypted env. Bare string = resolvable but no network-egress authority; object form pins the secret to allowed_hosts so @posthog/http-request may send it there.'
        )
        .default([]),
    limits: SpecLimitsSchema.default({
        max_turns: 50,
        max_tool_calls: 200,
        max_wall_seconds: 15 * 60,
        max_memory_mb: 512,
        max_cpu_cores: 0.25,
        max_open_approvals: 10,
    }),
    reasoning: ReasoningEffortSchema.describe(
        'Spec-wide default reasoning effort, applied to every model unless a model policy entry overrides it. Omit for the provider default.'
    ).optional(),
    framework_prompt: FrameworkPromptConfigSchema.describe(
        'Advanced: tune or pin the framework-injected system-prompt preamble. Rarely needed.'
    ).optional(),
    resume: ResumeConfigSchema.describe(
        'Per-agent resumability — keep completed sessions reachable longer than the platform default (e.g. a Slack thread watched across a whole sprint).'
    ).optional(),
})

export type AgentSpec = z.infer<typeof AgentSpecSchema>
export type ModelEntry = z.infer<typeof ModelEntrySchema>
export type ModelLevel = z.infer<typeof ModelLevelSchema>
export type ModelOptimizeFor = z.infer<typeof ModelOptimizeForSchema>
export type ModelPolicy = z.infer<typeof ModelPolicySchema>

/** Priority-ordered models the runner tries (primary first). Reasoning: per-entry → auto override → spec default. */
export function modelPolicyToList(spec: Pick<AgentSpec, 'models' | 'reasoning'>): ModelEntry[] {
    const policy = spec.models
    if (policy.mode === 'manual') {
        return policy.models.map((m) => ({ model: m.model, reasoning: m.reasoning ?? spec.reasoning }))
    }
    return MODEL_POLICY_LEVELS[policy.level].map((model) => ({
        model,
        reasoning: policy.reasoning ?? spec.reasoning,
    }))
}

export type Trigger = z.infer<typeof TriggerSchema>
export type TriggerType = Trigger['type']

/** Auth config for a trigger, or null for intrinsic-auth triggers (slack/cron)
 *  which authenticate via their own protocol rather than `AuthMode`s. */
export function triggerAuthConfig(trigger: Trigger): AuthConfig | null {
    if (trigger.type === 'webhook' || trigger.type === 'chat' || trigger.type === 'mcp') {
        return trigger.auth
    }
    return null
}
export type ToolRef = z.infer<typeof ToolRefSchema>
export type ApprovalPolicy = z.infer<typeof ApprovalPolicySchema>
export type McpRef = z.infer<typeof McpRefSchema>
export type McpToolEntry = z.infer<typeof McpToolEntrySchema>
export type SecretRef = z.infer<typeof SecretRefSchema>

/** Extract the secret name from a `spec.secrets[]` entry regardless of form. */
export function secretRefName(ref: SecretRef): string {
    return typeof ref === 'string' ? ref : ref.name
}

/**
 * Resolve a secret's `allowed_hosts` binding by name. Returns:
 *   - `string[]` when the secret is declared in object form with hosts.
 *   - `null` when the secret is declared as a bare string (no host binding —
 *     refused by `@posthog/http-request` at substitution time).
 *   - `undefined` when the name isn't declared in `spec.secrets[]` at all.
 *
 * The three-way return is load-bearing: the runtime treats `null` (declared
 * but unbound) as "fail-closed" — a bare-string secret can't be substituted
 * into an outbound request until it's pinned to an allowed host.
 */
export function getSecretAllowedHosts(spec: AgentSpec, name: string): readonly string[] | null | undefined {
    for (const ref of spec.secrets) {
        if (typeof ref === 'string') {
            if (ref === name) {
                return null
            }
        } else if (ref.name === name) {
            return ref.allowed_hosts
        }
    }
    return undefined
}

/**
 * Match a URL host against a `spec.secrets[].allowed_hosts[]` entry. Two forms:
 *   - exact: `slack.com` matches `slack.com` only (case-insensitive).
 *   - suffix wildcard: `*.example.com` matches `foo.example.com`,
 *     `a.b.example.com`; does NOT match bare `example.com`.
 *
 * Comparison is lowercase + ASCII. `host` is expected to be the parsed
 * `URL.host` (no port, no userinfo); strip those at the call site if needed.
 */
export function secretHostMatches(pattern: string, host: string): boolean {
    const p = pattern.toLowerCase()
    const h = host.toLowerCase()
    if (p.startsWith('*.')) {
        const suffix = p.slice(1) // ".example.com"
        return h.endsWith(suffix) && h.length > suffix.length
    }
    return p === h
}

/**
 * Strict principal match: same kind + same identifying key. Used at the
 * trigger edge (`/send`, Slack-thread resumes) to keep one user's session
 * scoped to that user, and by the runner's per-asker approval shortcut to
 * recognise the session principal posting follow-ups to their own session.
 * Lifted into agent-shared from ingress in PR 7 so the runner can reuse it
 * without crossing the ingress boundary.
 */
export function principalsMatch(stored: SessionPrincipal | null, incoming: SessionPrincipal | null): boolean {
    if (!stored && !incoming) {
        return true
    }
    if (!stored || !incoming) {
        return false
    }
    if (stored.kind !== incoming.kind) {
        return false
    }
    switch (stored.kind) {
        case 'anonymous':
            return true
        case 'posthog':
            return (
                incoming.kind === 'posthog' &&
                stored.user_id === incoming.user_id &&
                stored.team_id === incoming.team_id
            )
        case 'jwt':
            return incoming.kind === 'jwt' && stored.sub === incoming.sub
        case 'slack':
            return (
                incoming.kind === 'slack' &&
                stored.workspace_id === incoming.workspace_id &&
                stored.slack_user_id === incoming.slack_user_id
            )
        case 'posthog_internal':
            return incoming.kind === 'posthog_internal' && stored.team_id === incoming.team_id
        case 'shared_secret':
            // One secret == one trust principal. Per-caller isolation is the
            // `jwt` mode's job (forge-resistant `sub`); a self-asserted header
            // here would be a false security boundary.
            return incoming.kind === 'shared_secret' && stored.team_id === incoming.team_id
        case 'service':
            return (
                incoming.kind === 'service' &&
                (stored.id != null && incoming.id != null
                    ? stored.id === incoming.id
                    : stored.team_id === incoming.team_id)
            )
    }
}
export type SkillRef = z.infer<typeof SkillRefSchema>
export type ReasoningEffort = z.infer<typeof ReasoningEffortSchema>
export type FrameworkPromptSection = z.infer<typeof FrameworkPromptSectionSchema>
export type FrameworkPromptConfig = z.infer<typeof FrameworkPromptConfigSchema>
export type ResumeConfig = z.infer<typeof ResumeConfigSchema>

export type RevisionState = 'draft' | 'ready' | 'live' | 'archived'

export interface AgentApplication {
    id: string
    team_id: number
    slug: string
    name: string
    description: string
    live_revision_id: string | null
    archived: boolean
}

export interface AgentRevision {
    id: string
    application_id: string
    parent_revision_id: string | null
    /** Posthog user id (Django FK). Null for revisions created outside the auth flow (tests, system). */
    created_by_id: number | null
    created_at: string
    state: RevisionState
    bundle_uri: string
    bundle_sha256: string | null
    spec: AgentSpec
    /**
     * Encrypted JSON env block — the secret values this revision runs with.
     * Decrypted at session start by the runner's secret resolver (same
     * `EncryptedFields` key schedule as before). Lives on the revision (not
     * the application) so a draft preview runs against its own secrets,
     * isolated from the live revision. NULL means "no secrets set".
     */
    encrypted_env: string | null
}

/**
 * Same shape as `AgentRevision` but with the raw JSONB spec. Used by reads
 * that only need state / bundle pointers, or that overwrite the spec
 * wholesale — they shouldn't fail on schema drift in a row that's about
 * to be replaced. The strict-parse path stays on `AgentRevision`.
 */
export interface AgentRevisionRaw extends Omit<AgentRevision, 'spec'> {
    spec: unknown
}

/**
 * Session-bound identity — **never carries tokens**. Tokens live in the
 * `CredentialBroker` keyed by session_id; this struct is the persisted
 * "who" answer that the ACL machinery + audit log consume.
 *
 * Discriminated by `kind`; each variant carries whatever fields uniquely
 * identify that principal type. New auth modes should add a new variant
 * here rather than overloading existing ones.
 */
export type SessionPrincipal =
    | { kind: 'anonymous' }
    /** PostHog credential (PAT today, OAuth later) — resolves through `/api/users/@me/`. */
    | {
          kind: 'posthog'
          user_id: string
          user_uuid?: string
          team_id: number
          email?: string
          scopes?: string[]
      }
    /** JWT signed with the agent's configured secret. `sub` + `claims`
     *  are author-defined; the platform treats them as opaque. */
    | {
          kind: 'jwt'
          issuer_secret_ref: string
          sub: string
          claims: Record<string, unknown>
      }
    /**
     * Slack user resolved through the slack integration. Pure Slack
     * identity only — any cross-platform linkage (e.g. "this Slack user
     * maps to a PostHog user") is a credential-resolution concern, not
     * an identity property. The broker resolves `posthog_api` for a
     * Slack principal by looking up `agent_user_id → posthog user →
     * stored auth`; if nothing's stored, the broker returns null and
     * the tool degrades.
     */
    | {
          kind: 'slack'
          workspace_id: string
          slack_user_id: string
          agent_user_id?: string
      }
    /** Internal / service-to-service caller (PostHog backend → ingress). */
    | { kind: 'posthog_internal'; team_id?: number }
    /** Shared-secret bearer (webhook-style). One secret == one trust principal —
     *  every holder of the agent's secret is the same principal, and they share
     *  a single session space within the agent. The `x-external-key` header
     *  routes a request to an existing session by correlation id; it is a
     *  routing tag, NOT a credential, so do NOT treat it as a security
     *  boundary. Use `jwt` mode when you need per-caller isolation. */
    | { kind: 'shared_secret'; team_id?: number }
    /** Cron / scheduler / other system principals. */
    | { kind: 'service'; team_id?: number; id?: string }

/**
 * One slot in a session's ACL allowlist. Exactly one of `principal` or
 * `scope` is populated. `scope` is the "anyone matching this rule" form;
 * v0 ships the storage and the matcher but no UI populates it yet.
 */
export type SessionAclScope =
    | { kind: 'team_members'; team_id: number }
    | { kind: 'org_admins'; org_id: string }
    | { kind: 'slack_channel'; channel_id: string; workspace_id: string }

export interface SessionAclEntry {
    principal?: SessionPrincipal
    scope?: SessionAclScope
    granted_by: SessionPrincipal
    granted_at: string
    /** ISO timestamp; null means no expiry. */
    expires_at: string | null
    reason: string | null
    state: 'active' | 'revoked'
    revoked_by?: SessionPrincipal
    revoked_at?: string
    revoked_reason?: string
    /** v2: whether this grantee can grant further elevation. Default false. */
    can_delegate?: boolean
}

/**
 * A record of a rejected attempt to advance a session. Populated by the
 * ingress when `requireAclAccess` denies an incoming principal. v1 surfaces
 * these in the chat UI / Slack elevation message and lets the session owner
 * grant access (which moves the entry to `granted` and re-queues the
 * proposed message into `pending_inputs`).
 */
export interface PendingElevationRequest {
    id: string
    requester: SessionPrincipal
    requester_display: string
    trigger: 'chat' | 'webhook' | 'slack' | 'mcp'
    proposed_message: ConversationMessage
    created_at: string
    state: 'pending' | 'granted' | 'declined' | 'expired'
    decision_at?: string
    decision_by?: SessionPrincipal
}

export interface SessionUsageTotal {
    tokens_in: number
    tokens_out: number
    cache_read: number
    cache_write: number
    cost_input: number
    cost_output: number
    cost_cache_read: number
    cost_cache_write: number
    cost_total: number
}

export const EMPTY_USAGE_TOTAL: SessionUsageTotal = {
    tokens_in: 0,
    tokens_out: 0,
    cache_read: 0,
    cache_write: 0,
    cost_input: 0,
    cost_output: 0,
    cost_cache_read: 0,
    cost_cache_write: 0,
    cost_total: 0,
}

export interface AgentSession {
    id: string
    application_id: string
    revision_id: string
    team_id: number
    external_key: string | null
    /**
     * General-purpose dedupe key — "same request, no-op on collision."
     * Distinct from `external_key` (which means "same conversation, append
     * on collision"). Cron firings set it to `cron:<rev>:<name>:<minute>`;
     * webhook triggers can forward provider-supplied keys (Stripe, GitHub,
     * Slack). A partial unique index on `(application_id, idempotency_key)`
     * enforces at most one live session per key. Janitor sweep clears keys
     * older than 30 days so the partial index stays compact. Null for
     * sessions that pre-date the column or didn't supply a key. See plan
     * `cron-trigger-scheduler.md` §6.
     */
    idempotency_key: string | null
    /** Trigger-specific metadata stamped at enqueue, discriminated on `kind`. */
    trigger_metadata: TriggerMetadata | null
    /**
     * Session state. See the session-restart redesign for the contract:
     *
     *   queued    — awaiting a worker claim.
     *   running   — claimed; worker actively driving the turn.
     *   completed — agent finished its turn, session is OPEN. /send
     *               re-queues. Default end-of-turn state (natural stop,
     *               meta-end-turn).
     *   closed    — sealed by `meta-end-session`. Terminal. /send returns
     *               410 unless the trigger config sets `allow_restart`.
     *   cancelled — user invoked `/cancel`. Terminal. Same lifecycle
     *               semantics as `failed` (terminal regardless of
     *               `allow_restart`) but distinguishable in the UI and
     *               in observability so a user-initiated cancel isn't
     *               confused with a runtime error.
     *   failed    — error state. Terminal regardless of `allow_restart`.
     */
    state: 'queued' | 'running' | 'completed' | 'closed' | 'cancelled' | 'failed'
    /**
     * Principal that authenticated `/run`. Subsequent `/send` calls must
     * carry a principal that matches (same kind + id). Null for sessions
     * started without auth on public agents.
     */
    principal: SessionPrincipal | null
    /**
     * The active conversation history. Built up turn-by-turn. Uses pi-ai's
     * Message shape verbatim so the runner can hand it straight to `complete()`.
     */
    conversation: ConversationMessage[]
    /**
     * Inputs that arrived while a turn was in flight. The runner drains this
     * into `conversation` at the start of the next turn. Lets `/send` calls
     * during a running turn be durable without contending on the active
     * conversation list. See docs/native-refactor.md (queued-followups).
     */
    pending_inputs: ConversationMessage[]
    /**
     * Times the janitor has re-queued this session after a stuck-running
     * detection. Past the configured threshold the session is failed instead
     * (poison-pill handling). 0 for fresh sessions.
     */
    retry_count: number
    /**
     * Append-only running totals updated by the runner after every assistant
     * turn. Lets list / rollup queries read cost off a single column instead
     * of walking the conversation JSONB. Backfilled from `conversation` for
     * sessions created before this column existed.
     */
    usage_total: SessionUsageTotal
    /**
     * Allowlist of additional principals (or scopes) on top of `principal`.
     * Empty by default. Consulted by `requireAclAccess` on every resume / send.
     * v0 has no UI to populate this; v1 adds the grant surface.
     */
    acl: SessionAclEntry[]
    /**
     * Rejected attempts to advance this session. Each entry preserves the
     * proposed message so a grant can replay it. v0 records these; v1
     * surfaces them in the chat UI / Slack thread.
     */
    pending_elevation_requests: PendingElevationRequest[]
    created_at: string
    updated_at: string
}

/**
 * One message in a session's conversation. Structurally identical to pi-ai's
 * `Message` so the runner can pass `conversation` directly as
 * `Context.messages`. We re-declare it (rather than `import type`) to keep
 * agent-shared-v2 free of a forced dependency on pi-ai at the import site.
 */
export type ConversationMessage = UserMessage | AssistantMessageRecord | ToolResultMessage

export interface UserMessage {
    role: 'user'
    content: string | (TextContent | ImageContent)[]
    timestamp: number
    /**
     * Who sent this message. Populated by the ingress on every trigger that
     * accepts a user message (chat /run + /send, webhook, slack events, mcp
     * tools/call). Optional for backwards compatibility with existing rows;
     * absent on messages predating per-message principal stamping.
     *
     * Distinct from `AgentSession.principal` (the SESSION owner). When the
     * session ACL admits multiple principals (B.1), each message carries the
     * specific sender so per-asker authorisation (the gated-tool flow in #23)
     * can resolve "who's currently asking the bot to do X?"
     */
    sender?: SessionPrincipal
}

/**
 * Renamed to AssistantMessageRecord to avoid colliding with pi-ai's exported
 * AssistantMessage type when consumers re-export both.
 */
export interface AssistantMessageRecord {
    role: 'assistant'
    content: (TextContent | ThinkingContent | ToolCall)[]
    api?: string
    provider?: string
    model?: string
    usage?: {
        input: number
        output: number
        cacheRead?: number
        cacheWrite?: number
        totalTokens?: number
        cost?: { input?: number; output?: number; cacheRead?: number; cacheWrite?: number; total?: number }
    }
    stopReason?: 'stop' | 'length' | 'toolUse' | 'error' | 'aborted'
    errorMessage?: string
    timestamp: number
}

export interface ToolResultMessage {
    role: 'toolResult'
    toolCallId: string
    toolName: string
    content: (TextContent | ImageContent)[]
    isError: boolean
    timestamp: number
}

export interface TextContent {
    type: 'text'
    text: string
}

export interface ImageContent {
    type: 'image'
    data: string
    mimeType: string
}

export interface ThinkingContent {
    type: 'thinking'
    thinking: string
    thinkingSignature?: string
    redacted?: boolean
}

export interface ToolCall {
    type: 'toolCall'
    id: string
    name: string
    arguments: Record<string, unknown>
}

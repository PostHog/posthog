# Proposal: minted per-agent Slack apps

Status: draft proposal, not yet scheduled.
Owner: agent platform.

## Problem

Getting a Slack-triggered agent live today is the worst setup flow on the platform.
The runtime side is solid: the `slack` trigger, per-agent ingress URLs, signature verification, and the `TRIGGER_REQUIRED_SECRETS` promote gate all work well.
But provisioning is roughly ten manual steps across two admin UIs (see the `setting-up-slack-app` playbook): create a Slack app by hand, copy the signing secret, pick scopes, install, copy the bot token, punch out two secrets, promote, and only then paste two Request URLs back into Slack.
The promote-before-URL ordering trap is the single most common source of confusion.

The goal: a user should be able to say

> @PostHog please create me a new slack agent named @JokerHog who tells jokes

and end up with a live agent that has its own bot identity (name, avatar, @-handle), with exactly one manual step remaining (clicking Authorize on the install).

## Prior art

### How vercel/eve does it

Eve's `eve channels add slack` wizard (`packages/eve/src/setup/slackbot.ts`) orchestrates Vercel Connect, a first-party managed connector service:
create a connector (`vercel connect create slack`, which opens a browser OAuth flow), poll the connector until workspace metadata appears (3s interval, 5 minute timeout), then attach the connector's webhook destination to the app's route.
At runtime `connectSlackCredentials()` returns `{ botToken, webhookVerifier }`, with rotation and verification handled by the service.

The key observation: **eve never creates Slack apps**.
Every eve agent in a workspace speaks through the one shared Vercel connector identity.
Eve traded away per-agent bot identity to avoid the hard part (app creation).
We want the opposite trade: distinct per-agent bots, which means we have to solve minting.

### What we have in-house

- A complete per-agent Slack runtime. Each agent already brings its own Slack app: signature verification per revision (`agent-ingress/src/triggers/slack.ts`), `trusted_workspaces` gating, per-agent events/interactivity URLs, and per-revision `SLACK_SIGNING_SECRET` / `SLACK_BOT_TOKEN` in `encrypted_env`.
- A deterministic manifest generator, `buildSlackManifest()` (`agent-shared/src/spec/slack-manifest.ts`), that derives OAuth scopes and bot event subscriptions from the trigger config and tool list, correct by construction.
- A promote-time provisioning precedent: `provision_posthog_identity_apps()` (`backend/logic/posthog_identity_app.py`) auto-creates an `OAuthApplication` and injects its `client_id` into the frozen spec. Idempotent, org-locked, promote-hooked.
- A conversational front door: the PostHog Slack app (`products/slack_app`) already turns @-mentions into PostHog Code tasks, and PostHog Code already drives the full `agent-applications-*` MCP tool surface.

What we do not have: any programmatic creation of third-party apps, anywhere in the codebase.
This proposal adds that capability class, and treats its new trust surface accordingly.

### The Slack API facts this design rests on

- `apps.manifest.create` creates a Slack app from a JSON manifest, which is exactly what `buildSlackManifest()` already produces.
- The manifest API authenticates with an **app configuration token**: scoped to a user plus workspace (not to an app), 12 hour expiry, refreshed via `tooling.tokens.rotate`, which returns a new access token and a new refresh token. A service holding the refresh token can rotate indefinitely. This rotating pair is our equivalent of Vercel Connect's backend credential.
- Installation cannot be automated. Minting an app does not produce a bot token; a workspace member must click Authorize once per agent. One click is the floor.

Two facts need empirical confirmation in a spike (Slack's reference docs are ambiguous):
whether the `apps.manifest.create` response includes the app's credentials (client id/secret and, critically, the signing secret), and whether the manifest's events `request_url` is reachability-checked at create time.

## Design

### Architecture in one paragraph

The PostHog Slack app stays exactly what it is, the conversational front door and mediator, and gains no agent-runtime responsibilities.
A new **minting service** inside `products/agent_platform` holds per-workspace config token pairs and calls Slack's manifest API to stamp out a dedicated Slack app per agent.
Because every minted app is a normal per-agent app, the existing runtime needs almost nothing: the `slack` trigger, per-agent URLs, per-revision secrets, and the promote gate are all unchanged.
The minting service fills in what a human fills in today.
This also avoids a shared-app dispatcher entirely: no central events URL, no channel-binding router, no bot identity multiplexing. Per-agent apps make Slack itself the router.

### The @JokerHog flow, end to end

1. **Ask.** `@PostHog please create me a new slack agent named @JokerHog who tells jokes` in any channel. A new intent branch in `products/slack_app` mention handling seeds a builder task with the agent-authoring playbooks, and the builder agent authors the spec (slack trigger, `mention_only` plus `auto_resume_threads`, joke-telling `agent.md`).
2. **Mint.** The builder agent calls a new `slack-app-mint` endpoint for the draft revision. The minting service resolves the workspace's config token pair (rotating if near expiry), renders `buildSlackManifest()` with the agent's name and real per-slug URLs, calls `apps.manifest.create`, and persists the returned app id plus credentials, writing the signing secret (and client id/secret) into the revision's `encrypted_env`. No human sees a secret.
3. **URL verification without the ordering trap.** One small ingress change: answer Slack's `url_verification` challenge for any known revision whose signing secret is set, not just live ones. The secret exists before Slack ever probes, so verification succeeds pre-promote. This also fixes the manual flow's worst trap for free.
4. **One click: install.** The bot posts back in the thread: "@JokerHog is ready, install to this workspace" with the minted app's OAuth authorize URL, `state`-bound to (team, application, revision). A new callback endpoint in agent_platform (registered in every minted manifest's redirect URLs) exchanges the code using the minted app's own client credentials and writes the `xoxb-` bot token into `encrypted_env`.
5. **Activate.** Callback completion triggers validate, freeze, and promote (the existing `TRIGGER_REQUIRED_SECRETS` gate now passes on its own), sets `trusted_workspaces` to the installing workspace id, then joins the requested public channels via `conversations.join` (the `channels:join` scope goes into every minted manifest). Private channels get an "/invite @JokerHog" note in the thread.
6. **Use.** `@JokerHog tell me a joke`. Its own bot, its own identity, the existing runtime path.

Total human actions after the ask: one Authorize click, plus channel picks if prompted.

### Routing

With per-agent apps, routing among agents is free, since each has its own @-handle.
What remains is the PostHog app as concierge:

- Mention-prefix on @PostHog for lifecycle verbs: create / list / status / pause / delete an agent. A new intent branch alongside the existing directives; everything else falls through to normal behavior.
- Channel scoping at creation: "create @JokerHog for #jokes and #random" captures channels, auto-joins after install, and optionally sets `channel_id` on the trigger config.
- Per-agent trigger knobs (`mention_only`, `auto_resume_threads`, `ack_reaction`) default to the conversational-bot pairing from the playbook.

### Workspace enrollment, the one ceremony that remains

Config tokens cannot be obtained via OAuth.
A workspace member with app-creation rights generates the token pair on Slack's app settings page once and hands it to us through a first-class one-time punch-out ("Enable Slack agent minting for this workspace": deep link, then paste into a PostHog form, never into chat).
Enrollment is triggered lazily the first time someone asks @PostHog for an agent in an unenrolled workspace.
After that, unlimited mints.
This is the honest cost of per-agent identity versus eve's shared-app model, paid once per workspace rather than per agent.

### What happens to the manual (BYO) flow

Nothing is torn out, and nothing new is built for it.
The runtime is the per-agent-app runtime either way; the manual flow is just "a human did the minting service's job by hand".
The manifest generator, the `set_secret` punch-out, and the `setting-up-slack-app` playbook remain as the escape hatch (self-hosted instances without a minting path, custom edge cases), and the playbook's happy path points at minting.

## Build plan

### Spike (2 to 3 days, before committing to phase A)

With a scratch config token against a test workspace, confirm:

1. The `apps.manifest.create` response fields, especially whether the signing secret is returned. If not, the mint step needs a follow-up call or a fallback human copy, which changes the UX floor.
2. Create-time request URL validation behavior.
3. Rate limits at realistic mint volume.
4. That the collaborator/ownership model of config-token-minted apps does not bite when the enrolling user leaves the workspace (likely mitigation: recommend enrolling with a service account).

### Phase A: minting service (all in `products/agent_platform/backend/`)

- Model `SlackWorkspaceAppConfig(team, slack_workspace_id, sensitive_config, created_by, status)`, team-scoped, unique per (team, workspace), with the token pair in an encrypted field. Rotation is the delicate part: refresh tokens are single-use, so rotate under `select_for_update` (the `provision_posthog_identity_apps` locking pattern), proactively before expiry, and treat a failed rotation as "workspace minting disabled, re-enroll", surfaced on the Connections tab, never a silent retry loop.
- Model `AgentSlackApp(team, application, slack_app_id, slack_workspace_id, status: minted | installed | revoked)`, the connector record; drives status UI and teardown (`apps.manifest.delete` on agent deletion, best effort).
- `logic/slack_app_minting.py`: mint, update (re-run `apps.manifest.update` when the trigger config changes scope needs, for example enabling DMs, and tell the user to reinstall), delete. All Slack calls go through `posthog/egress/` per the repo rule (new `slack/` incarnation, GitHub is the reference), from Django. This is control-plane work; the node services never touch it.
- Django endpoints plus regenerated MCP tools: `slack-app-mint`, `slack-app-status`, `slack-workspace-enroll-status`. Rerun `hogli build:openapi` after.

### Phase B: install and activation

- OAuth callback endpoint for minted apps: state-bound, per-app client credentials, writes the bot token to `encrypted_env`, kicks validate / freeze / promote, auto-joins channels.
- Ingress: answer `url_verification` for non-live revisions with a resolvable signing secret.
- Failure surfaces: install abandoned (nudge in thread after a timeout), token revoked later (Slack `tokens_revoked` event marks the `AgentSlackApp` revoked, with a Connections-tab warning and a thread notification).

### Phase C: the conversational front door

- Mention-intent branch in `products/slack_app` for agent lifecycle, seeding a builder task. In-thread progress messages ("minted, waiting for install, live") come from the task, keeping `slack_app` itself thin: it gains an intent router and nothing else. All agent knowledge lives in agent_platform and the builder playbooks.
- Rewrite the `setting-up-slack-app` playbook around minting; add a `minting-slack-agents` playbook for the builder agent.

### Testing and rollout

- e2e cases in `services/agent-tests/` for the ingress challenge change and the callback-driven promote.
- Django tests for rotation races and mint idempotency (a re-mint must not orphan apps).
- Feature-flag the whole path; dogfood by minting an internal test agent first.

Rough sizing: spike 2 to 3 days, phase A about 2 weeks, phase B about 1 week, phase C 1 to 2 weeks. A and C can overlap once the spike settles the API contract.

## Risks, ranked

1. **Config token custody.** A workspace-scoped app-creation credential held server-side is a new trust surface. Encrypted storage, egress-gated calls, tight scoping, and activity logging on mint / install / revoke are non-negotiable, and this is the piece to socialize with security first.
2. **Slack-side unknowns.** The spike exists to kill these before any real build.
3. **Rotation fragility.** Single-use refresh tokens plus concurrency is the one place this can break silently. The locking plus explicit "re-enroll" failure mode handles it, but it needs a monitor (alert on rotation failures).
4. **Workspace app sprawl.** Every agent is a real Slack app in the workspace's app list. Mitigations: consistent naming and description stamping ("Managed by PostHog Agents"), `apps.manifest.delete` on teardown, and a minted-apps inventory on the Connections tab.

## Open questions

- Should enrollment recommend (or require) a service account as the config token owner, to survive the enrolling user leaving?
- Does `apps.manifest.update` on a live agent (for example adding the DM scopes) need an in-product "reinstall required" state, or is the thread nudge enough?
- Where does the minted-apps inventory live in the UI: per-agent Connections tab only, or also a workspace-level view?

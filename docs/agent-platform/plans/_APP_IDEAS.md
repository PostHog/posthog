# App ideas — candidate first-party agents

Freeform inbox of app-shaped ideas to build _on_ the agent platform.
Each entry is written tightly enough that an authoring AI with MCP
access could turn it into a working spec + bundle from the
description alone.
The checklist beneath each one is the gating question: **what
capability does the platform need before this app is buildable?**

Legend for the prerequisites checklist:

| Marker | Meaning                                                                                                  |
| ------ | -------------------------------------------------------------------------------------------------------- |
| ✅     | Shipped — capability exists in code today. Link to the implementation or operating doc.                  |
| 📋     | Planned — a sibling plan file exists. Link to it.                                                        |
| ⚠️     | **Gap** — neither built nor planned. Either a new plan needs writing or the app needs a different shape. |

Cross-cutting status (refreshed against current code):

- ✅ **Persistent agent memory** — `MemoryStore` interface +
  `S3MemoryStore` impl in
  [`services/agent-shared/src/memory/`](../../../services/agent-shared/src/memory/),
  with six native tools (`@posthog/memory-list / -search /
-read / -write / -update / -delete` in
  [`services/agent-tools/src/tools/memory.ts`](../../../services/agent-tools/src/tools/memory.ts)).
  Markdown + YAML frontmatter format with BM25 search via
  MiniSearch. Per-`(team, application)` scoped — every
  "remembers across sessions" bullet below now has a concrete
  primitive to lean on.
- ⚠️ **Per-user (per-principal) memory scope** — the memory layer
  scopes by `(teamId, applicationId)` only. There is no
  `scope: 'user:<principal_id>'` slot, so "agent remembers this
  individual user" use cases still degrade to "agent remembers
  the most-recent answer for everyone" without a shim. Still a
  gap; would need a key-prefix convention or a new field on
  `MemoryStore.write()`.
- ✅ **Skill templates** — registry of shared, versioned skills +
  custom-tool templates that agents pin via
  `spec.skills[].from_template` / `spec.tools[].from_template`.
  Backend, MCP write tools, freeze-time resolution, frontend
  pages, concierge skill — see
  [`skill-templates.md`](skill-templates.md).
- 📋 **Cron trigger** — schema slot exists in `TriggerSchema`,
  janitor side (the scheduler that fires sessions on schedule)
  is not implemented. Plan:
  [`cron-trigger-scheduler.md`](cron-trigger-scheduler.md).
  Every weekly / monthly app below assumes cron and is
  currently blocked on this — but it's a small piece of work.
- 📋 **Runtime MCP support (external endpoints)** —
  `McpRefSchema` accepts `{ kind: 'external', url }`, but the
  runner doesn't open external MCP clients at session start.
  Agent-to-agent MCP (`kind: 'agent'`) resolves through the
  ingress because the receiving agent's `/mcp` trigger exists.
  Plan: [`runtime-mcps.md`](runtime-mcps.md). Anything wanting
  GitHub / Stripe / Grafana / k8s / Warpstream is blocked here
  until this lands — but most of those have MCP servers, so it
  unblocks several apps at once.
- ⚠️ **Document / corpus ingestion + retrieval** — multiple apps
  want a curated, periodically-refreshed corpus to ground
  against. `web-fetch` + `web-search` cover ad-hoc retrieval;
  no curated-corpus primitive. Could be served by the memory
  store if a corpus-loader job is added, but the indexing
  semantics differ from per-agent notes.
- ⚠️ **Inbound email mailbox per agent** — no email trigger,
  no plan.
- ⚠️ **Spreadsheet / structured-report output sink** —
  no Sheets / Notion / Airtable native tool, no plan.
- ⚠️ **Agent-to-agent invocation (outbound)** — the receiving
  half is shipped (agent-as-MCP), the calling-from-an-agent
  half needs a `@posthog/ass/trigger-agent` native or the
  runtime-MCP path open to point at another platform agent's
  `/mcp` endpoint. Not a separate plan today.
- ⚠️ **Connecting an agent to a user's local machine** — the
  client-fulfilled-tools protocol (`kind: 'client'`) is shipped
  and used today by the agent-console for `focus_*` / `toast` /
  `set_secret`. The shape supports local-fs / local-git tools
  in principle; what's missing is a **CLI client** that hosts
  them. No plan today.
- ⚠️ **Call-transcription integration** (Gong / Otter / Fireflies)
  and **incentive distribution** (Tremendous / Amazon gift
  cards) — no plan, no MCP server we'd reach for once runtime
  MCP lands.

---

## SRE Slack bot — alert investigator

**Status:** infant version built — see
[`services/agent-tests/src/examples/sre-slack-bot/`](../../../services/agent-tests/src/examples/sre-slack-bot/).
Regression test at
[`example-sre-bot.test.ts`](../../../services/agent-tests/src/cases/example-sre-bot.test.ts).

**Description.** Slack-resident agent that PostHog engineers can
either `@mention` or that auto-triggers when an alerting system
posts to a designated `#alerts-*` channel. On invocation it pulls
logs (PostHog + Grafana), runbook content, and prior-incident
notes, walks through a structured triage flow, and proposes
remediation steps in-thread. After resolution it captures the
outcome ("symptom X was actually root cause Y; mitigation Z worked")
so the next time a similar alert fires it can short-circuit the
investigation. Higher-trust actions (k8s exec, restarting pods)
are gated behind explicit human approval.

**Spec sketch.**

```yaml
triggers:
    - type: slack # @mention from engineers + alert channels
    - type: webhook # Grafana alerting → POST /agents/sre/webhook
tools:
    - kind: native, id: '@posthog/query' # PostHog logs
    - kind: native, id: '@posthog/web-fetch' # runbook URLs
    - kind: native, id: '@posthog/slack-post-message' # thread replies
    - kind: native, id: '@posthog/slack-read-channel'
    - kind: native, id: '@posthog/slack-read-thread'
    - kind: native, id: '@posthog/slack-react'
    - kind: native, id: '@posthog/table-query' # recall prior incidents
    - kind: native, id: '@posthog/table-append' # record resolved outcome
    - kind: native, id: '@posthog/table-membership' # cheap seen-set check
mcps: []
# v1: Grafana + Kubernetes MCPs are private. Cloudflare Tunnel exposes
# them with a public hostname; register each as kind: 'external'.
# Tracked separately — not on this branch.
skills:
    - triage-playbook
    - slack-thread-protocol
limits: { max_turns: 30, max_wall_seconds: 600 }
reasoning: high
```

**Platform prerequisites.**

- [x] ✅ Slack trigger (mention + channel-scoped) —
      [`spec.ts`](../../../services/agent-shared/src/spec/spec.ts#L13)
      `TriggerSchema` `slack` variant, ingress at
      [`slack.ts`](../../../services/agent-ingress/src/triggers/slack.ts).
- [x] ✅ Webhook trigger (for the alerting system to fire it) —
      [`webhook.ts`](../../../services/agent-ingress/src/triggers/webhook.ts).
- [x] ✅ PostHog logs / query tool —
      [`posthog-query.v1.ts`](../../../services/agent-tools/src/tools/posthog-query.v1.ts).
- [x] ✅ Approval-gated tools for k8s exec / pod restarts —
      [`approval-gated-tools.md`](approval-gated-tools.md).
- [x] ✅ Per-session access elevation (Slack thread-reply
      identity gap is closed) —
      [`per-session-access-elevation.md`](per-session-access-elevation.md).
- [x] ✅ Long-running sessions for multi-day incident threads —
      [`long-running-sessions.md`](long-running-sessions.md).
- [x] ✅ Persistent agent memory — prose `MemoryStore` (`@posthog/memory-*`)
      and deterministic `TabularStore` (`@posthog/table-*`) both ship.
      SRE bot uses the tabular variant for the "alert signature →
      outcome" pattern (one row per resolved incident, dedupe on
      thread_url); the prose variant is reserved for free-form
      lessons-learned notes.
- [ ] 📋 Runtime MCP support for Grafana + k8s servers — **Cloudflare
      Tunnel is the planned v1 path**, separate from this branch.
      Exposes each private MCP behind a public hostname; agent spec
      registers the tunneled hostname as a `kind: 'external'` McpRef,
      so the runtime side ([`runtime-mcps.md`](runtime-mcps.md)) is
      already shipped — only the deploy machinery is missing.
      [`tailscale-mcps.md`](tailscale-mcps.md) is parked.
- [ ] ⚠️ Runbook corpus retrieval — `web-fetch` works for a
      single URL but the agent needs a grounded index over the
      whole runbook tree. Memory store could host a periodic
      mirror; no loader job today. **Gap.**

**Feasibility today.** **Both v0 and v1-with-memory shipped on this
branch.** Bundle at
[`services/agent-tests/src/examples/sre-slack-bot/`](../../../services/agent-tests/src/examples/sre-slack-bot/),
e2e at
[`example-sre-bot.test.ts`](../../../services/agent-tests/src/cases/example-sre-bot.test.ts).
Next upgrade is **Grafana / k8s MCPs over Cloudflare Tunnel** — a
separate PR that adds the deploy recipe + an integration row for the
tunnel hostname; no runner changes required.

---

## Wake-me-up — daily briefing agent

**Status:** infant version built — see
[`services/agent-tests/src/examples/wake-me-up/`](../../../services/agent-tests/src/examples/wake-me-up/).
Regression test at
[`example-wake-me-up.test.ts`](../../../services/agent-tests/src/cases/example-wake-me-up.test.ts).

**Description.** A personal morning briefing agent. Fires on a
weekday cron at 08:00 PT, optionally also on `@mention` from Slack,
and produces a categorised briefing covering PostHog signals,
GitHub PRs awaiting the user's review, monitored Slack channels,
and yesterday's carry-over items. Writes a full markdown report
into the agent's memory store, then projects a condensed mrkdwn
version into a configured personal Slack channel. Inspired by the
author's local Claude-Code skill of the same shape; this version
runs on the platform without the user being awake.

**Spec sketch.**

```yaml
triggers:
    - type: cron
      config:
          name: morning-brief
          schedule: '0 8 * * 1-5'
          timezone: 'America/Los_Angeles'
          prompt: 'Build the morning briefing for {fired_at:date}.'
          external_key: 'wake-me-up:{fired_at:date}'
    - type: slack # on-demand re-runs
    - type: chat # ad-hoc iteration from the console
tools:
    - kind: native, id: '@posthog/query'
    - kind: native, id: '@posthog/web-fetch'
    - kind: native, id: '@posthog/web-search'
    - kind: native, id: '@posthog/slack-post-message'
    - kind: native, id: '@posthog/slack-read-channel'
    - kind: native, id: '@posthog/memory-search'
    - kind: native, id: '@posthog/memory-write'
    - kind: native, id: '@posthog/memory-read'
    - kind: native, id: '@posthog/table-query' # carry-over discovery
    - kind: native, id: '@posthog/table-append' # briefings index
mcps: []
# Public external MCPs (GitHub MCP, Linear MCP, …) are valid additions
# via kind: 'external' — runtime-mcps PR 7 already handles them.
skills:
    - briefing-template
    - carry-over
    - slack-post-format
limits: { max_turns: 40, max_wall_seconds: 600 }
reasoning: high
```

**Platform prerequisites.**

- [x] ✅ Cron trigger — `TriggerSchema` `cron` variant +
      `cron-tick.ts` scheduler. Placeholder expansion (`{fired_at:date}`)
      lives in the trigger schema; `external_key` enables daily
      idempotency.
- [x] ✅ Slack + chat triggers — both shipped.
- [x] ✅ PostHog query, web-fetch, web-search, slack-\* native tools.
- [x] ✅ Both memory primitives — prose (`@posthog/memory-*`) for
      the full markdown briefing, tabular (`@posthog/table-*`) for
      the per-day index that powers carry-over.
- [x] ✅ Skills with frontmatter descriptions — load-on-demand via
      `@posthog/load-skill` keeps the system prompt small even when
      the agent has many specialised pieces.
- [ ] ⚠️ User-maintained config in memory (channels.yml,
      relevance.yml, teammates.yml) — works today via
      `@posthog/memory-write` for the user, `@posthog/memory-read`
      for the agent. No tooling helps the user maintain it though;
      a small console panel would lift this to "fully wired."

**Feasibility today.** **Shipped on this branch.** Same e2e
regression net as the SRE bot — load bundle, fire trigger
(`cronTick` in tests, real `setInterval` in prod), drain, assert
the right tools fired in the right order, prove the briefing row
plus markdown landed in real S3. Extension paths are pure spec edits:
add a `kind: 'external'` McpRef for GitHub MCP to replace
`web-fetch` against the GitHub REST API; widen the cron to multiple
times per day; switch the model to `reasoning: low` for cost
savings.

---

## AI documentation agent — Slack + website + chat

**Description.** Inkeep-style assistant grounded against PostHog's
public docs + an internal runbook corpus. Reachable from three
surfaces: the public docs site, an in-product chat dock, and a
Slack `@docs-bot`. Answers a user's question by querying the doc
corpus, citing sources, and (when the user is an approved Slack
org member) writing back into the corpus — "you were wrong about
X" → the bot proposes a docs-update PR or a memory note for next
time. Two memory tiers: an **internal-only** memory (org members
only) and a **per-user** memory ("Ben usually means the Node SDK
when he says `posthog-js`").

**Spec sketch.**

```yaml
triggers:
  - type: slack
  - type: chat # embedded on posthog.com/docs + in-product
tools:
  - '@posthog/web-search' # public docs index
  - '@posthog/query' # internal usage analytics for examples
  - '@posthog/memory/recall' # ⚠️ scope = agent | user
  - '@posthog/memory/write' # ⚠️ approval-gated for internal scope
  - '@posthog/github/open-pr' # ⚠️ no native tool today
skills:
  - cite-sources
  - tier-permission-check
auth: { mode: 'public' } # public docs, identity flows from chat
```

**Platform prerequisites.**

- [x] ✅ Slack trigger — see SRE bot above.
- [x] ✅ Chat trigger (embeddable) —
      [`chat.ts`](../../../services/agent-ingress/src/triggers/chat.ts);
      the embeddable React surface ships via `@posthog/agent-chat`
      per [`agent-console-website.md`](agent-console-website.md) §11.
- [x] ✅ Per-session principal carries the user identity (so
      "approved Slack org member" can be checked) —
      [`per-session-access-elevation.md`](per-session-access-elevation.md).
- [x] ✅ Approval-gated tools for memory-write into the internal
      tier — [`approval-gated-tools.md`](approval-gated-tools.md);
      `@posthog/memory-write` accepts an `approval_policy` override.
- [x] ✅ Persistent agent memory (internal scope) — `MemoryStore`
      keyed by `(team, application)`; the "agent-wide" tier maps
      to a flat path prefix.
- [ ] ⚠️ **Per-user memory scope** — `MemoryStore` doesn't accept
      a principal segment in the key; "Ben usually means…"
      requires a shim or a small extension. **Gap.**
- [ ] ⚠️ Curated doc corpus + retrieval (more than `web-fetch`) —
      could be a periodic memory-store loader, but no job exists
      and the indexing semantics drift from per-agent notes.
      **Gap.**
- [ ] ⚠️ Native GitHub "open PR with these changes" tool —
      **gap**. Will be served via [`runtime-mcps.md`](runtime-mcps.md)
      once that ships, since GitHub has an MCP server.

**Feasibility today.** Buildable as **org-only internal Slack
bot first** — the public-docs surface needs the chat-trigger
embeddable variant on posthog.com/docs (separate frontend
work) and a curated doc corpus (gap). Memory + approval gating
let the org-internal "remember Ben prefers Node SDK" flow work
right now without per-user scope, by writing notes with a
`user:ben@posthog.com` tag in the body — until per-user scope
lands as a first-class field.

---

## Wizard for ASS — agent-platform authoring concierge

**Description.** An agent _on_ ASS that builds other ASS agents.
Drives a user through the optimal authoring flow described in
[`agent-authoring-flow.md`](agent-authoring-flow.md) — discovery,
spec scaffolding, secrets, bundle authoring, test runs, promotion.
Server-side variant (the chat dock from
[`agent-console-website.md`](agent-console-website.md)) lands first.
The local-CLI variant (commits to the user's local Git checkout)
needs a way to reach the user's filesystem, which the platform
doesn't have a story for yet.

**Spec sketch.**

```yaml
triggers:
  - type: chat
tools:
  - kind: native, id: '@posthog/ass/list-agents'     # ⚠️ MCP exposes this
  - kind: native, id: '@posthog/ass/create-revision' # ⚠️ same
  - kind: native, id: '@posthog/ass/test-run'        # ⚠️ same
  - kind: client, from_native: '@posthog/ui/focus'   # navigates the console
  - kind: client, id: 'local-fs/write-file'          # local-CLI variant
  - kind: client, id: 'local-git/commit'             # local-CLI variant
skills:
  - agent-authoring-flow  # the reference skill
```

**Platform prerequisites.**

- [x] ✅ Chat trigger + embeddable dock —
      [`agent-console-website.md`](agent-console-website.md).
- [x] ✅ Agent-as-MCP-server (the wizard agent calls the platform's
      MCP under the user's principal) —
      [`agent-as-mcp-server.md`](agent-as-mcp-server.md).
- [x] ✅ Per-session principal threading so wizard actions show up
      as the user in the activity log —
      [`per-session-access-elevation.md`](per-session-access-elevation.md).
- [x] ✅ Authoring skill + reference flow — the agent-concierge
      bundle at
      [`services/agent-tests/src/examples/agent-concierge/`](../../../services/agent-tests/src/examples/agent-concierge/)
      is the reference; `skills/authoring-new-agents.md`,
      `skills/editing-agents-safely.md`,
      `skills/using-the-registry.md` cover the flow.
- [x] ✅ Client-fulfilled tools protocol — `kind: 'client'`
      variant in
      [`spec.ts`](../../../services/agent-shared/src/spec/spec.ts);
      `focus_*` / `toast` / `get_context` / `set_secret`
      handlers live in
      [`services/agent-console/src/components/Dock.tsx`](../../../services/agent-console/src/components/Dock.tsx).
- [ ] ⚠️ Local-CLI client that hosts `local-fs/*` + `local-git/*`
      client-fulfilled tools — no plan for this client today.
      **Gap** for the local variant; not blocking for server-side.

**Feasibility today.** Server-side variant is **buildable now**
— concierge bundle ships, all referenced client tools are wired
in the console, the registry lets it pull canonical authoring
skills via `from_template`. The local-CLI variant still wants
a CLI client to host `local-fs` / `local-git` tools.

---

## Marketing update agent

**Description.** Reads merged PRs (per product area), Slack
discussions in product channels, and weekly standup summaries.
Decides what's marketing-worthy ("we shipped a new SDK feature, a
visible pricing tweak, a customer-named integration"). Posts a
draft into a marketing channel for human curation; once approved,
compiles a per-product weekly changelog and a draft announcement
("blog post starter / tweet thread / email blurb").

**Spec sketch.**

```yaml
triggers:
  - type: cron
    config: { schedule: '0 14 * * THU', timezone: 'US/Pacific' }
tools:
  - '@posthog/github/list-prs' # ⚠️ no native tool
  - '@posthog/slack/read-channel' # ⚠️ slack.v1.ts only posts today
  - '@posthog/slack/post'
  - '@posthog/memory/write' # ⚠️ for per-product changelog rollups
skills:
  - changelog-aggregator
  - marketing-voice
```

**Platform prerequisites.**

- [ ] 📋 Cron trigger — schema slot exists; scheduler not built.
      Plan:
      [`cron-trigger-scheduler.md`](cron-trigger-scheduler.md).
- [x] ✅ Slack post tool —
      [`slack.v1.ts`](../../../services/agent-tools/src/tools/slack.v1.ts).
- [ ] 📋 Runtime MCP (the GitHub MCP server covers PR listing) —
      [`runtime-mcps.md`](runtime-mcps.md).
- [x] ✅ Slack read-channel + read-thread —
      [`slack.v1.ts`](../../../services/agent-tools/src/tools/slack.v1.ts)
      `slackReadChannelV1` / `slackReadThreadV1`.
- [x] ✅ Persistent agent memory for per-product weekly
      changelog rollups.

**Feasibility today.** **Blocked on two small pieces**: cron
scheduler + GitHub access via runtime MCP. Both are planned, not
gaps. Slack-only variant (no PR list — humans paste links) is
buildable as a webhook-triggered draft today.

---

## Feature prioritization agent

**Description.** Watches the GitHub Projects board (in-flight
features), the public posthog/posthog issues with the
`enhancement` label, and customer-facing Slack channels for
feature requests. Weekly digest into the product channel
bucketed as: **in-flight** (linked to a PR), **getting attention**
(>N mentions this week, no PR), **forgotten** (>30d quiet on a
historically-busy thread). Known hard part: deduping the same
feature referenced different ways across the three sources.

**Spec sketch.**

```yaml
triggers:
  - type: cron
    config: { schedule: '0 16 * * MON' }
tools:
  - '@posthog/github/list-projects' # ⚠️
  - '@posthog/github/list-issues' # ⚠️
  - '@posthog/slack/read-channel' # ⚠️
  - '@posthog/memory/recall' # ⚠️ for fuzzy-match across sources
  - '@posthog/memory/write'
skills:
  - feature-canonicalization
  - bucket-classifier
reasoning: high # the dedup is the hard part
```

**Platform prerequisites.**

- [ ] 📋 Cron trigger.
- [ ] 📋 GitHub access via runtime MCP —
      [`runtime-mcps.md`](runtime-mcps.md).
- [x] ✅ Slack read-channel — see Marketing agent.
- [x] ⚠️ Persistent agent memory — `MemoryStore` ships BM25
      search via MiniSearch, which handles the
      canonicalization-by-fuzzy-token problem well enough for a
      v0. **True vector / embedding search isn't shipped** —
      mark as `partial`. Acceptable for v0; revisit when the
      dedup quality plateaus.

**Feasibility today.** Same blockers as Marketing agent: cron +
runtime MCP for GitHub. Memory primitive is good-enough for the
dedup. Buildable end-of-month if cron lands.

---

## Competitive pricing agent

**Description.** Stores PostHog's pricing RFCs as ground truth.
Periodically (every 6 months, or on-demand) crawls competitor
pricing pages, diffs against the previous snapshot, and surfaces
deltas. Composes with the PostHog data warehouse: pulls anonymized
customer billing + usage rows, simulates "what would this customer
pay under proposed pricing model X", and outputs an incremental-
revenue projection per scenario. Highest-leverage PM activity
currently done by hand.

**Spec sketch.**

```yaml
triggers:
  - type: cron
    config: { schedule: '0 0 1 */6 *' } # every 6 months
  - type: webhook # on-demand "rerun scenario X"
tools:
  - '@posthog/web-fetch' # competitor pages
  - '@posthog/query' # billing + usage
  - '@posthog/sandbox/python' # ⚠️ for the simulation math
  - '@posthog/memory/recall' # ⚠️ pricing RFCs + last-snapshot
  - '@posthog/memory/write'
  - '@posthog/sheets/write' # ⚠️ scenario output
skills:
  - pricing-simulation
  - rfc-grounding
```

**Platform prerequisites.**

- [ ] 📋 Cron trigger.
- [x] ✅ Webhook trigger.
- [x] ✅ PostHog query tool.
- [x] ✅ Web-fetch for competitor pages.
- [x] ✅ Sandboxed code execution for simulation math —
      [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md).
- [x] ✅ Persistent agent memory for pricing RFCs + last-period
      snapshot — store as memory notes, retrieve via
      `memory-search`.
- [ ] ⚠️ **Spreadsheet / structured-report output** for scenarios.
      **Gap.** Workaround: write the simulation output as a
      memory note and have the user pull it into Sheets manually.

**Feasibility today.** Webhook-triggered (on-demand) variant
is **buildable now** with the on-demand fallback for the missing
Sheets sink. The "every 6 months" cron variant waits on the
cron scheduler.

---

## Industry intelligence agent

**Description.** Builds a data-warehouse table of industry signal
by reading customer changelogs, public release notes, and
subscribed newsletters. Users configure interests
("AI infra", "observability", "B2B SaaS pricing"); the agent
generates personalised weekly summaries. Stretch: trigger alerts
when a specific competitor ships something flagged as relevant.

**Spec sketch.**

```yaml
triggers:
  - type: cron
    config: { schedule: '0 8 * * MON' }
  - type: email # ⚠️ no email trigger today
tools:
  - '@posthog/web-fetch'
  - '@posthog/warehouse/insert' # ⚠️ no native write tool
  - '@posthog/memory/recall' # ⚠️ user interests
  - '@posthog/memory/write'
skills:
  - signal-extraction
  - interest-personalisation
```

**Platform prerequisites.**

- [ ] 📋 Cron trigger.
- [x] ✅ Web-fetch.
- [ ] ⚠️ **Inbound email trigger / per-agent mailbox** for
      newsletter subscription. **Gap.**
- [x] ⚠️ Persistent agent memory exists; **per-user scope is
      missing** — "Ben likes observability content" works only
      via in-body tagging until per-principal scope lands.
- [ ] ⚠️ **Native data-warehouse write tool** (current `@posthog/query`
      is read-only). **Gap.** Workaround: write summaries to
      memory + render via a Notebook later.

**Feasibility today.** **Two real gaps** (email trigger,
warehouse write) and one nice-to-have (per-user scope). Could
ship as a cron-fired (once cron lands) Slack-output app
with user interests in a memory file editable by hand —
slimmer than the original vision but viable.

---

## Customer research agent

**Description.** Listens to / reads customer call transcripts,
generates case-study drafts, identifies insights that don't
otherwise make it back to product teams ("3 customers this week
mentioned the same friction with X"). Long-running so it can
cross-reference last quarter's transcripts.

**Spec sketch.**

```yaml
triggers:
  - type: webhook # transcription service POSTs here
  - type: cron # weekly synthesis pass
tools:
  - '@posthog/transcripts/fetch' # ⚠️ no native transcription integration
  - '@posthog/memory/recall' # ⚠️ cross-session insight clustering
  - '@posthog/memory/write'
  - '@posthog/slack/post'
skills:
  - insight-clustering
  - case-study-template
```

**Platform prerequisites.**

- [ ] 📋 Cron trigger.
- [x] ✅ Webhook trigger.
- [x] ✅ Long-running sessions —
      [`long-running-sessions.md`](long-running-sessions.md);
      `ResumeConfigSchema` in spec, `resume.enabled` flag with
      `max_completed_age_ms` (default 7 days, raisable per
      agent).
- [ ] ⚠️ **Call transcription integration** (Gong / Otter / etc.) —
      no native tool, no MCP server we'd target once runtime
      MCP lands. **Gap.** Workaround: webhook trigger ingests
      transcripts the transcription provider posts.
- [x] ⚠️ Persistent agent memory shipped; semantic / vector
      search not (MiniSearch BM25 only). Insight clustering
      works at v0 quality.

**Feasibility today.** Buildable as a **webhook-fed variant**
where the transcription service POSTs to `/agents/<slug>/webhook`
with the transcript inline. Long-running sessions + memory let
the cross-quarter synthesis pass work. No native transcription
tool needed.

---

## AI user interviewing agent

**Description.** Conducts user interviews via an embeddable chat
(survey-style). Hits a target N participants, stores each
respondent's answers keyed by their PostHog identity, then runs an
analysis pass over the corpus. Approval system gates incentive
distribution (e.g. $25 Amazon credit). Template system for common
interview types (NPS-style, onboarding, churn diagnosis).

**Spec sketch.**

```yaml
triggers:
  - type: chat # embedded on app.posthog.com
tools:
  - '@posthog/memory/write' # ⚠️ per-respondent answers
  - '@posthog/query' # event context for the respondent
  - '@posthog/incentive/issue' # ⚠️ no incentive integration
skills:
  - interview-template:nps
  - interview-template:onboarding
  - response-analyzer
```

**Platform prerequisites.**

- [x] ✅ Chat trigger + embeddable dock —
      [`agent-console-website.md`](agent-console-website.md) §11
      (`@posthog/agent-chat`).
- [x] ✅ Per-respondent identity via principal —
      [`per-session-access-elevation.md`](per-session-access-elevation.md).
- [x] ✅ Approval-gated tools for incentive distribution —
      [`approval-gated-tools.md`](approval-gated-tools.md).
- [x] ✅ Skill templates — see
      [`skill-templates.md`](skill-templates.md); registry
      lets the agent pin a canonical "interview template" via
      `from_template`.
- [x] ⚠️ Persistent agent memory shipped but **per-respondent
      scope is missing** — respondents would have to share a
      single memory pool until per-principal scope lands. v0
      workaround: prefix path with respondent id.
- [ ] ⚠️ **Incentive distribution integration** (Tremendous,
      Amazon gift cards, etc.) — **gap**. Could be a custom
      tool the user wires today with their own API key.

**Feasibility today.** **Buildable as a v0** with skill
templates handling interview library, memory + path-prefixing
covering per-respondent answers, and a user-authored custom
tool wrapping Tremendous's API. Per-principal scope upgrade
later.

---

## Growth review automation

**Description.** Replaces the manual weekly/monthly "growth review"
data-pull. Knows the canonical PostHog warehouse queries that
underlie each review section, runs them, formats results into the
existing review template (spreadsheet or doc). When a metric is
missing because instrumentation doesn't exist, kicks off a PostHog
code session (file an issue / open a draft PR via the coding agent
in [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md))
rather than silently dropping it.

**Spec sketch.**

```yaml
triggers:
  - type: cron
    config: { schedule: '0 9 * * MON' }
tools:
  - '@posthog/query'
  - '@posthog/sheets/write' # ⚠️
  - '@posthog/ass/trigger-agent' # ⚠️ fan-out to coding agent
skills:
  - growth-review-template
  - missing-instrumentation-handler
```

**Platform prerequisites.**

- [ ] 📋 Cron trigger.
- [x] ✅ PostHog query tool.
- [x] ✅ Sandboxed code execution / coding-agent target for
      "fix the missing instrumentation" —
      [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md).
- [ ] ⚠️ **Agent-to-agent invocation** ("trigger the coding
      agent from here") — receiving half (agent-as-MCP)
      shipped; outbound call from inside an agent still
      missing. Could be served by runtime MCP pointing at the
      other agent's `/mcp` once it lands. Track as gateway
      plan v2.
- [ ] ⚠️ **Spreadsheet output sink**. **Gap.** Workaround:
      output to a Slack post / Notebook / memory note.

**Feasibility today.** **Buildable as a webhook-fed v0**
(weekly cron lands later) that posts the review to Slack
or writes to a Notebook instead of Sheets. Coding-agent
fan-out comes after agent-to-agent outbound — until then,
flag missing instrumentation in the report and the user
opens issues by hand.

---

## Gap analysis agent

**Description.** Reads through user-interview transcripts (from
the customer research agent) + support tickets + the open issues
list, compares against shipped features and in-flight PRs, and
surfaces the actual product gaps that nobody is working on.
Filters out anything already in-flight. Output feeds other
agents (e.g. the user-interview agent picks gap topics for its
next round).

**Spec sketch.**

```yaml
triggers:
  - type: cron
tools:
  - '@posthog/memory/recall' # ⚠️ shared corpus with customer-research
  - '@posthog/github/list-prs' # ⚠️
  - '@posthog/zendesk/list-tickets' # ⚠️
  - '@posthog/ass/trigger-agent' # feed gap list downstream
skills:
  - gap-classifier
  - in-flight-deduper
```

**Platform prerequisites.**

- [ ] 📋 Cron trigger.
- [ ] 📋 GitHub + ticketing access via runtime MCP —
      [`runtime-mcps.md`](runtime-mcps.md).
- [ ] ⚠️ Agent-to-agent invocation (see Growth review).
- [x] ⚠️ Persistent agent memory shipped per-agent;
      **cross-agent shared corpus** (shared with the Customer
      research agent) is missing. `MemoryStore` keys include
      `applicationId` so two agents can't read from the same
      pool. **Gap.** Workaround: pick one of the two agents as
      the corpus owner and have the other query via MCP.

**Feasibility today.** **Blocked on cron + runtime MCP** for
real data sources. Memory can be made to work via the "single
owner agent" workaround. Without the data sources, only the
gap-classifier logic is exercisable — not enough to ship.

---

## Financial reconciliation agent

**Description.** Connects Stripe + a banking provider + (optionally)
an accounting system. Periodically reconciles charges vs payouts,
flags discrepancies, and proposes journal entries. Generic enough
that the "business agent" framing applies to companies that aren't
PostHog — the example use case the platform can ship as a template.

**Spec sketch.**

```yaml
triggers:
  - type: cron
    config: { schedule: '0 6 * * *' }
tools:
  - '@posthog/memory/recall'             # ⚠️ prior reconciliation state
  - '@posthog/memory/write'
mcps:
  - id: stripe,  endpoint: '<stripe mcp>'    # ⚠️ runtime not wired
  - id: banking, endpoint: '<plaid/mercury mcp>'
skills:
  - reconciliation-policy
  - discrepancy-classifier
```

**Platform prerequisites.**

- [ ] 📋 Cron trigger.
- [ ] 📋 Runtime MCP — [`runtime-mcps.md`](runtime-mcps.md).
      Once wired, every external financial provider with an MCP
      server drops in.
- [x] ✅ Persistent agent memory — cross-run reconciliation
      state lives naturally as memory notes (per-period
      snapshot keyed by date).

**Feasibility today.** **Blocked entirely on runtime MCP** —
no Stripe / banking data without it. Cron is a smaller piece;
memory's done. This is a great showcase agent the moment
runtime MCP lands.

---

## Warpstream forecasting tool

**Description.** Pulls all Warpstream invoices + per-cluster costs
(via Warpstream's API or MCP), cross-references with Grafana
metrics for usage growth, and projects forward — "at current
growth, this cluster crosses $X/mo in three months". Mirrors the
shape of the SRE bot but operates on cost data instead of incident
data.

**Spec sketch.**

```yaml
triggers:
  - type: cron
    config: { schedule: '0 10 * * MON' }
tools:
  - '@posthog/sandbox/python'                # forecasting math
  - '@posthog/memory/write'                  # historical projections
mcps:
  - id: warpstream, endpoint: '<warpstream api/mcp>'   # ⚠️
  - id: grafana,    endpoint: '<grafana mcp>'          # ⚠️
skills:
  - cost-forecasting
```

**Platform prerequisites.**

- [ ] 📋 Cron trigger.
- [x] ✅ Sandboxed code execution for forecasting math —
      [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md).
- [ ] 📋 Runtime MCP for Warpstream + Grafana —
      [`runtime-mcps.md`](runtime-mcps.md).
- [x] ✅ Persistent agent memory — last-period snapshot lands
      as a memory note keyed by ISO week.

**Feasibility today.** Same shape as Financial reconciliation:
**blocked on runtime MCP**. The forecasting math + memory both
exist; the data sources don't.

---

## Feasibility matrix

| App                            | Verdict (now)                                                    | What's missing                                           |
| ------------------------------ | ---------------------------------------------------------------- | -------------------------------------------------------- |
| SRE Slack bot                  | ✅ v0 + v1 (memory) shipped this branch                          | Grafana / k8s via Cloudflare Tunnel (separate PR)        |
| Wake-me-up daily briefing      | ✅ v0 shipped this branch                                        | User-config console panel (nice-to-have)                 |
| AI documentation agent         | 🟡 Internal-only Slack v0 ships; public docs surface waits       | Per-user memory scope + curated doc corpus               |
| Wizard for ASS (server)        | ✅ Ship today                                                    | —                                                        |
| Wizard for ASS (local-CLI)     | 🔴 Blocked                                                       | CLI client to host `local-fs` / `local-git` tools        |
| Marketing update agent         | 🟡 Slack-only v0 via webhook; full vision waits                  | Runtime MCP (GitHub)                                     |
| Feature prioritization agent   | ✅ Cron + webhook v0 ships now                                   | Runtime MCP (GitHub) for the curated review surface      |
| Competitive pricing agent      | ✅ Cron + webhook v0 ships now                                   | Sheets sink (use memory note)                            |
| Industry intelligence agent    | 🔴 Two-gap blocked                                               | Email trigger + warehouse-write                          |
| Customer research agent        | ✅ Webhook v0 ships now                                          | Per-respondent scope is nice-to-have, not blocking       |
| AI user interviewing agent     | ✅ v0 ships now via skill templates + custom tool for Tremendous | Native incentive integration is convenience, not blocker |
| Growth review automation       | ✅ Cron + webhook v0 ships now                                   | Agent-to-agent outbound for the fan-out variant          |
| Gap analysis agent             | 🟡 Cron half ships; data-source MCPs missing                     | Runtime MCP for ticketing & GitHub                       |
| Financial reconciliation agent | 🟡 Cron half ships; data-source MCPs missing                     | Runtime MCP for Stripe + banking                         |
| Warpstream forecasting tool    | 🟡 Cron half ships; data-source MCPs missing                     | Runtime MCP for Warpstream + Grafana                     |

Legend: ✅ build now · 🟡 v0 buildable with a stripped scope ·
🔴 blocked on a sibling plan.

## Promotion candidates — refreshed

Highest-leverage next picks given the matrix:

1. **Wizard for ASS (server-side)** — the only fully-unblocked
   "showcase the platform" candidate; the agent-concierge bundle
   already covers most of it, registry + chat dock land the rest.
2. **Cloudflare Tunnel recipe for SRE bot v2** — exposes Grafana
   and Kubernetes MCPs behind a public hostname so the existing
   `kind: 'external'` McpRef works as-is. No runner changes; pure
   ops/deploy work. Separate PR from this branch.
3. **Competitive pricing agent (cron variant)** — ships now
   end-to-end on cron + sandbox + query + web-fetch + memory.
   Uses the same skeleton the wake-me-up bundle proves out.

**What's shipped vs. what's left.** This branch closed the two
biggest blocks on the matrix:

- **Cron scheduler** ([`cron-trigger-scheduler.md`](cron-trigger-scheduler.md))
  ✅ shipped. Unblocked the time-based half of Marketing, Feature
  prioritization, Industry intel, Customer research, Growth
  review, Gap analysis, Financial reconciliation, Warpstream
  forecasting. **8 apps.**
- **Runtime MCP (external)** ([`runtime-mcps.md`](runtime-mcps.md))
  ✅ shipped. Public MCPs (Sentry, GitHub-public, Linear, anything
  with `.well-known/oauth-protected-resource`) work via
  `kind: 'external'`. Private MCPs (Grafana, k8s, internal
  services) need a public hostname — Cloudflare Tunnel is the
  v1 path on the SRE bot example; broader rollout is a deploy
  recipe, not platform work.
- **Persistent agent memory** ✅ shipped (prose + tabular). The
  SRE bot uses the tabular variant for incident outcomes; the
  wake-me-up bundle uses both (markdown briefing + per-day
  index row).

The remaining 🔴-classified apps all share the same gap:
**runtime MCP for a specific provider's data**, with each
provider also requiring an OAuth integration row in Django. The
runner side is done; landing each provider is a small
integration PR, not a platform investment.

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

Cross-cutting gaps surfaced by this inbox (promote into their own
plans once we commit):

- ⚠️ **Persistent agent memory** — every "remembers" bullet below
  (SRE outcomes, doc updates, customer profiles, pricing RFCs,
  weekly changelogs) wants a first-class memory store on the
  platform. Today the only persistence agents have is
  `agent_session.conversation` JSONB (per-session, evictable).
  Discussed in
  [`resumable-conversations.md`](resumable-conversations.md) for
  conversation continuity, but a cross-session **key-value /
  vector store keyed by `(agent, scope)`** is not designed
  anywhere yet. Needs its own plan.
- ⚠️ **Per-user (per-principal) memory scope** — distinct from
  agent-wide memory. "Agent remembers individual users for
  better context" / "stores responses in memory for later
  analysis" both need a `scope: 'user:<principal_id>'` slot on
  whatever the memory primitive ends up being. Composes with
  the principal model from
  [`per-session-access-elevation.md`](per-session-access-elevation.md)
  but is a memory-layer concern, not an ACL one.
- ⚠️ **Document / corpus ingestion + retrieval** — multiple
  apps want "query existing documentation", "read changelogs",
  "subscribe to newsletters". `web-fetch` + `web-search` cover
  ad-hoc fetches; what's missing is a curated corpus an agent
  is grounded against, with periodic refresh.
- ⚠️ **Inbound email mailbox per agent** — "subscribes to
  newsletters", "reads email updates" needs an addressable
  mailbox that triggers a session on receive. No trigger type
  for email today.
- ⚠️ **Spreadsheet / structured-report output sink** — "outputs
  to spreadsheets or structured reports" wants a typed artifact
  sink (Google Sheets, Notion DB, etc.) rather than only inline
  tool_result content. Composes with the artifact channel from
  [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md)
  §"artifact channel" but that's intra-session; persisted
  artifacts to external systems aren't covered.
- ⚠️ **Connecting an agent to a user's local machine** (filesystem,
  local git, local kubectl context) — server agents can't reach
  out to a developer's laptop today. The closest existing
  pattern is the **client-fulfilled tools** protocol from
  [`agent-console-website.md`](agent-console-website.md) §8 —
  the client (CLI / IDE / desktop app) declares `client.handles[]`
  and the runner routes the call back over SSE. That's the
  natural shape for "local fs / local git" tools but no
  CLI client exists yet to host them.

---

## SRE Slack bot — alert investigator

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
  - type: slack          # @mention from engineers + alert channels
  - type: webhook        # Grafana alerting → POST /agents/sre/webhook
tools:
  - kind: native, id: '@posthog/query'        # PostHog logs
  - kind: native, id: '@posthog/web-fetch'    # runbook URLs
  - kind: native, id: '@posthog/slack/post'   # thread replies
  - kind: native, id: '@posthog/memory/recall' # ⚠️ doesn't exist
  - kind: native, id: '@posthog/memory/write'  # ⚠️ doesn't exist
mcps:
  - id: grafana,    endpoint: '<grafana mcp>' # ⚠️ runtime wiring not shipped
  - id: kubernetes, endpoint: '<k8s mcp>'     # ⚠️ same
skills:
  - triage-playbook
  - postmortem-template
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
- [ ] 📋 Runtime MCP support for Grafana + k8s servers —
      [`runtime-mcps.md`](runtime-mcps.md).
      Schema slot exists; runner doesn't open the clients yet.
- [ ] ⚠️ **Persistent agent memory** — "remembers outcomes from
      previous alerts/incidents" requires cross-session storage
      keyed by alert signature → notes. **Gap.**
- [ ] ⚠️ Runbook corpus retrieval — `web-fetch` works for a
      single URL but the agent needs a grounded index over the
      whole runbook tree. **Gap.**

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
      tier — [`approval-gated-tools.md`](approval-gated-tools.md).
- [ ] ⚠️ **Persistent agent memory** (internal scope) — **gap**.
- [ ] ⚠️ **Per-user memory** (user scope) — **gap**.
- [ ] ⚠️ Curated doc corpus + retrieval (more than `web-fetch`) —
      **gap**.
- [ ] ⚠️ Native GitHub "open PR with these changes" tool —
      **gap**. Could be served via [`runtime-mcps.md`](runtime-mcps.md)
      once that ships, since GitHub has an MCP server.

---

## Wizard for ASS — agent-stack authoring concierge

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
- [ ] 📋 Authoring skill + reference flow —
      [`agent-authoring-flow.md`](agent-authoring-flow.md).
- [ ] 📋 Client-fulfilled tools protocol (so server-side variant
      can drive console navigation; foundational for the
      local-CLI variant too) —
      [`agent-console-website.md`](agent-console-website.md) §8.
- [ ] ⚠️ Local-CLI client that hosts `local-fs/*` + `local-git/*`
      client-fulfilled tools — no plan for this client today.
      **Gap** for the local variant; not blocking for server-side.

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

- [x] ✅ Cron trigger —
      [`cron-trigger-scheduler.md`](cron-trigger-scheduler.md).
- [x] ✅ Slack post tool —
      [`slack.v1.ts`](../../../services/agent-tools/src/tools/slack.v1.ts).
- [ ] 📋 Runtime MCP (the GitHub MCP server covers PR listing) —
      [`runtime-mcps.md`](runtime-mcps.md).
- [x] ✅ Slack read-channel + read-thread —
      [`slack.v1.ts`](../../../services/agent-tools/src/tools/slack.v1.ts)
      `slackReadChannelV1` / `slackReadThreadV1`.
- [ ] ⚠️ **Persistent agent memory** for per-product weekly
      changelog rollups. **Gap.**

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

- [x] ✅ Cron trigger.
- [ ] 📋 GitHub access via runtime MCP —
      [`runtime-mcps.md`](runtime-mcps.md).
- [x] ✅ Slack read-channel — see Marketing agent.
- [ ] ⚠️ **Persistent agent memory** with semantic/fuzzy lookup
      (the canonicalization problem _is_ a vector-search problem).
      **Gap.**

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

- [x] ✅ Cron + webhook triggers.
- [x] ✅ PostHog query tool.
- [x] ✅ Web-fetch for competitor pages.
- [x] ✅ Sandboxed code execution for simulation math —
      [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md).
- [ ] ⚠️ **Persistent agent memory** for pricing RFCs + last-period
      snapshot. **Gap.**
- [ ] ⚠️ **Spreadsheet / structured-report output** for scenarios.
      **Gap.**

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

- [x] ✅ Cron trigger.
- [x] ✅ Web-fetch.
- [ ] ⚠️ **Inbound email trigger / per-agent mailbox** for
      newsletter subscription. **Gap.**
- [ ] ⚠️ **Persistent agent memory** with per-user scope (for
      configured interests). **Gap.**
- [ ] ⚠️ **Native data-warehouse write tool** (current `@posthog/query`
      is read-only). **Gap.**

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

- [x] ✅ Cron + webhook triggers.
- [x] ✅ Long-running sessions —
      [`long-running-sessions.md`](long-running-sessions.md).
- [ ] ⚠️ **Call transcription integration** (Gong / Otter / etc.) —
      no native tool, no MCP for these yet. **Gap.**
- [ ] ⚠️ **Persistent agent memory** with semantic search for
      insight clustering. **Gap.**

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
- [ ] 📋 Skill templates (for "interview template" library shape) —
      [`skill-templates.md`](skill-templates.md).
- [ ] ⚠️ **Persistent agent memory** scoped per-respondent +
      cross-respondent corpus query. **Gap.**
- [ ] ⚠️ **Incentive distribution integration** (Tremendous,
      Amazon gift cards, etc.) — **gap**.

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

- [x] ✅ Cron trigger.
- [x] ✅ PostHog query tool.
- [x] ✅ Sandboxed code execution / coding-agent target for
      "fix the missing instrumentation" —
      [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md).
- [ ] 📋 **Agent-to-agent invocation** ("trigger the coding
      agent from here") — the auto-chaining gateway entry in
      [`_TODO.md`](_TODO.md#auto-chaining) covers the inbound
      side; outbound "agent X starts agent Y" wants the same
      primitive. Track as gateway plan v2.
- [ ] ⚠️ **Spreadsheet output sink**. **Gap.**

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

- [x] ✅ Cron trigger.
- [ ] 📋 GitHub + ticketing access via runtime MCP —
      [`runtime-mcps.md`](runtime-mcps.md).
- [ ] 📋 Agent-to-agent invocation (see Growth review).
- [ ] ⚠️ **Persistent agent memory** (shared corpus with
      Customer research agent — implies a memory _scope_ broader
      than a single agent, which the proposed memory primitive
      needs to support). **Gap.**

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

- [x] ✅ Cron trigger.
- [ ] 📋 Runtime MCP — [`runtime-mcps.md`](runtime-mcps.md).
      Once wired, every external financial provider with an MCP
      server drops in.
- [ ] ⚠️ **Persistent agent memory** for cross-run reconciliation
      state. **Gap.**

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

- [x] ✅ Cron trigger.
- [x] ✅ Sandboxed code execution for forecasting math —
      [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md).
- [ ] 📋 Runtime MCP for Warpstream + Grafana —
      [`runtime-mcps.md`](runtime-mcps.md).
- [ ] ⚠️ **Persistent agent memory** to compare current
      projections against last week's. **Gap.** (Could also be
      satisfied by a data-warehouse write tool — same workaround.)

---

## Promotion candidates

Apps that would be **buildable end-of-month** if we picked them up
right now, judged against the prerequisites above:

1. **SRE Slack bot** — buildable today _without_ memory and
   _without_ Grafana/k8s MCP, by leaning on `@posthog/query` for
   logs and Slack thread continuity as a soft memory substitute.
   Lossy but ships. Adding memory + runtime MCPs is the
   visible-improvement loop.
2. **Wizard for ASS (server-side variant)** — buildable today,
   blocked only on the chat dock landing
   ([`agent-console-website.md`](agent-console-website.md) phase
   v0.2). Local-CLI variant gated on a CLI client.
3. **Growth review automation** — buildable minus the spreadsheet
   sink (output to a doc or Slack message in v0).

Everything else is gated primarily on the **persistent memory**
gap — that's the single highest-leverage platform investment for
this inbox.
